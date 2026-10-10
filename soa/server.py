import asyncio, datetime, hashlib, ipaddress, json, os, socket, ssl, time
from aiohttp import web, WSMsgType
from . import config, localtts, tools, updater

WEB = config.ROOT / "web"


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def make_ssl():
    """Self-signed cert (phones need HTTPS to allow the mic). Regenerated if LAN IP changes."""
    cert, key, ipf = config.DATA / "cert.pem", config.DATA / "key.pem", config.DATA / "cert.ip"
    ip = lan_ip()
    if not (cert.exists() and key.exists() and ipf.exists() and ipf.read_text() == ip):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "son-of-anton")])
        now = datetime.datetime.utcnow()
        c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
             .not_valid_after(now + datetime.timedelta(days=3650))
             .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                            x509.IPAddress(ipaddress.ip_address(ip))]), False)
             .sign(k, hashes.SHA256()))
        cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
        key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                        serialization.NoEncryption()))
        ipf.write_text(ip)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    return ctx


class Server:
    def __init__(self, cfg, store, cloud, local, brain, improver, wake, bus):
        self.cfg, self.store, self.cloud, self.local = cfg, store, cloud, local
        self.brain, self.improver, self.wake, self.bus = brain, improver, wake, bus
        self.token = config.token()
        self.started = time.time()
        self.clients = {}
        self.ip = lan_ip()
        self.timers = {}
        self.upd = {"msg": "not checked"}
        self.pc_mic = False
        self.restart = None  # set by main
        self.edge_skip = 0.0       # when edge-tts failed (offline) skip it for a while
        self.mute_until = 0.0      # ignore the PC mic while Anton is talking (so he doesn't hear himself)
        self.browser_stt = 0.0     # last time the browser mic delivered speech (it wins over the PC mic)
        _emit = bus.emit

        def emit(t, **k):
            if t in ("reply", "ack") and k.get("to") in ("dashboard", "pc", "all"):
                self.mute_until = max(self.mute_until, time.time() + 1.2 + len(k.get("text", "")) * 0.075)
            return _emit(t, **k)
        bus.emit = emit

    # ---- speech in (from phone / browser / vosk) ----
    def on_speech(self, who, text):
        self.bus.emit("stt", who=who, text=text)
        t = self.timers.pop(who, None)
        if t:
            t.cancel()
        ev, payload = self.wake.feed(who, text)
        if ev == "wake":
            self.bus.emit("wake", who=who)
        if ev == "message":
            self._dispatch(who, payload)
        elif self.wake.listening(who) and self.cfg["auto_finish_seconds"]:
            self.timers[who] = asyncio.get_running_loop().call_later(self.cfg["auto_finish_seconds"], self._auto, who)

    def on_pc_speech(self, text):
        """Offline PC microphone (Vosk). Ignored while the browser mic works or while Anton is speaking."""
        now = time.time()
        if now < self.mute_until or now - self.browser_stt < 10:
            return
        self.on_speech("pc", text)

    def _auto(self, who):
        msg = self.wake.flush(who)
        if msg:
            self._dispatch(who, msg)

    def _dispatch(self, who, msg):
        self.bus.emit("heard", who=who, text=msg)
        asyncio.get_running_loop().create_task(self.brain.handle(msg, who))

    # ---- web ----
    @web.middleware
    async def auth(self, request, handler):
        tok = request.query.get("token") or request.cookies.get("soa")
        if tok != self.token:
            return web.Response(status=401, text="Unauthorized. Open the full URL printed in the terminal (it contains ?token=...).")
        resp = await handler(request)
        if request.query.get("token") and request.path != "/ws":
            resp.set_cookie("soa", self.token, max_age=86400 * 365, samesite="Lax")
        return resp

    async def voicejs(self, request):
        return web.Response(text=(WEB / "voice.js").read_text(encoding="utf-8"), content_type="application/javascript")

    async def page(self, request):
        f = "phone.html" if request.path == "/phone" else "dashboard.html"
        return web.Response(text=(WEB / f).read_text(encoding="utf-8"), content_type="text/html")

    def state(self):
        b = self.brain.stats
        ms = b["ms"]
        return {
            "name": self.cfg["name"], "uptime": int(time.time() - self.started),
            "local": {"ok": self.local.ok, "model": self.cfg["local"]["model"]},
            "models": self.cloud.catalog(), "pinned": self.cloud.pinned, "last_model": self.cloud.last,
            "idle": int(self.improver.idle), "improving": self.improver.running, "busy": self.brain.busy,
            "stats": {k: b[k] for k in ("instant", "local", "cloud", "agent")}, "avg_ms": int(sum(ms) / len(ms)) if ms else 0,
            "skills": [n for n, t in tools.TOOLS.items() if t.get("skill")], "tools": len(tools.TOOLS),
            "facts": self.store.memories("fact", 12), "notes": self.store.memories("note", 5),
            "habits": self.store.top_phrases(10), "cycles": self.store.memories("cycle", 8),
            "phone_url": f"https://{self.ip}:{self.cfg['tls_port']}/phone?token={self.token}",
            "convo": self.store.recent(30),
            "self_improve": self.cfg["self_improve"]["enabled"], "version": config.version(), "update": self.upd,
            "local_status": self.local.status, "pc_mic": self.pc_mic, "voice": self.cfg["tts"]["voice"],
            "keys": {k: bool(os.environ.get(k)) for k in self.key_names()},
        }

    def key_names(self):
        return [p["key_env"] for p in self.cfg["providers"]] + ["GITHUB_TOKEN"]

    async def _edge(self, text, v, p):
        if time.time() < self.edge_skip:
            return False
        try:
            import edge_tts
            await asyncio.wait_for(edge_tts.Communicate(text, v["voice"], rate=v["rate"]).save(str(p)), 12)
            return p.exists() and p.stat().st_size > 0
        except Exception:
            p.unlink(missing_ok=True)
            self.edge_skip = time.time() + 45
            return False

    async def tts(self, request):
        text = request.query.get("text", "").strip()[:400]
        if not text:
            return web.Response(status=400)
        v = self.cfg["tts"]
        key = hashlib.sha1((v["voice"] + v["rate"] + text).encode()).hexdigest()
        d = config.DATA / "tts"
        d.mkdir(exist_ok=True)
        mp3, wav = d / (key + ".mp3"), d / (key + ".wav")
        if mp3.exists() or await self._edge(text, v, mp3):
            return web.FileResponse(mp3, headers={"Cache-Control": "max-age=86400"})
        if wav.exists() or await asyncio.get_running_loop().run_in_executor(None, localtts.synth, text, wav):
            return web.FileResponse(wav, headers={"Cache-Control": "max-age=86400"})
        return web.Response(status=503)

    async def pregen(self):
        """Pre-render instant-reply voices so greetings play with zero delay (online only)."""
        from .fastpath import seed_texts
        v = self.cfg["tts"]
        d = config.DATA / "tts"
        d.mkdir(exist_ok=True)
        for t in seed_texts():
            p = d / (hashlib.sha1((v["voice"] + v["rate"] + t).encode()).hexdigest() + ".mp3")
            if not p.exists() and not await self._edge(t, v, p):
                return

    async def do_update(self, apply):
        loop = asyncio.get_running_loop()
        self.upd = await loop.run_in_executor(None, updater.check, self.cfg)
        if apply and self.upd.get("available"):
            self.bus.emit("improve", job="update", status="start")
            ok, msg = await loop.run_in_executor(None, updater.apply, self.cfg)
            self.upd = {**self.upd, "msg": msg}
            self.bus.emit("improve", job="update", status="done", result=msg)
            if ok and self.restart:
                self.restart()
        return self.upd

    async def api_state(self, request):
        return web.json_response(self.state())

    async def api_post(self, request):
        d = await request.json()
        act = request.match_info["act"]
        if act == "model":
            self.cloud.pinned = d.get("id") or None
        elif act == "improve":
            self.cfg["self_improve"]["enabled"] = bool(d.get("on"))
        elif act == "fast":
            self.brain.fast.add_hard(d["phrase"], d["reply"])
        elif act == "keys":
            if d["env"] in self.key_names() and d.get("value", "").strip():
                config.save_env(d["env"], d["value"].strip())
                asyncio.create_task(self.cloud.refresh())
        elif act == "test":
            lines = await self.cloud.test()
            await self.local.check()
            lines.append(f"local: {self.local.status} ({self.local.model})")
            lines.append("update: " + (await self.do_update(False))["msg"])
            return web.json_response({"lines": lines})
        elif act == "update":
            return web.json_response(await self.do_update(bool(d.get("apply"))))
        elif act == "clear":
            self.store.q("DELETE FROM convo", (), True)
            self.bus.log.clear()
        elif act == "forget":
            self.store.q("DELETE FROM memory WHERE kind='fact' AND text=?", (d["text"],), True)
        return web.json_response({"ok": True})

    async def ws(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        q = asyncio.Queue(maxsize=200)
        self.bus.subs.add(q)
        for ev in list(self.bus.log)[-40:]:
            q.put_nowait(ev)

        async def pump():
            while True:
                await ws.send_json(await q.get())
        task = asyncio.create_task(pump())
        try:
            async for m in ws:
                if m.type != WSMsgType.TEXT:
                    continue
                d = json.loads(m.data)
                who = (d.get("who") or "dashboard")[:24]
                if d.get("type") == "stt" or (d.get("type") == "say" and who == "pc"):
                    self.browser_stt = time.time()
                if d.get("type") == "say" and d.get("text", "").strip():
                    asyncio.create_task(self.brain.handle(d["text"].strip(), who))
                elif d.get("type") == "stt" and d.get("text"):
                    self.on_speech(who, d.get("text", ""))
        finally:
            task.cancel()
            self.bus.subs.discard(q)
        return ws

    async def start(self):
        app = web.Application(middlewares=[self.auth])
        app.add_routes([web.get("/", self.page), web.get("/phone", self.page), web.get("/ws", self.ws),
                        web.get("/api/state", self.api_state), web.get("/tts", self.tts), web.get("/voice.js", self.voicejs), web.post("/api/{act}", self.api_post)])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, self.cfg["host"], self.cfg["port"]).start()
        try:
            await web.TCPSite(runner, self.cfg["host"], self.cfg["tls_port"], ssl_context=make_ssl()).start()
        except Exception as e:
            print("HTTPS (phone mic) unavailable:", e)
        return runner
