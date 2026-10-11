import asyncio, json, os, re, shutil, subprocess, time
import httpx


def strip_think(t):
    return re.sub(r"<think>.*?</think>", "", t or "", flags=re.S).strip()


def is_free(m):
    mid = str(m.get("id", "")).lower()
    if any(x in mid for x in ("embed", "moderation", "whisper", "tts", "rerank")):
        return False
    pr = m.get("pricing") or {}
    try:
        if pr and float(pr.get("prompt", 1)) == 0 and float(pr.get("completion", 1)) == 0:
            return True
    except (TypeError, ValueError):
        pass
    return mid.endswith(":free") or "/free" in mid or "-free" in mid


def vision_flag(m):
    mods = (m.get("architecture") or {}).get("input_modalities") or m.get("input_modalities") or []
    if mods:
        return "image" in mods
    return True if re.search(r"vl\b|vision|omni|pixtral|llava|gemini|gpt-[45]|claude", str(m.get("id", "")), re.I) else None


SLOWISH = re.compile(r"reason|think|r1\b|deepseek-r|qwq|120b|235b|405b|ultra|preview", re.I)


class _HTTP(Exception):
    def __init__(self, code, retry=None):
        super().__init__(f"HTTP {code}")
        self.code, self.retry = code, retry


class Cloud:
    """OpenAI-compatible multi-provider client, auto-failover across free models, vision-aware."""
    def __init__(self, cfg):
        self.cfg, self.cool, self.pinned, self.last, self.entries = cfg, {}, None, None, []
        self.stat = {}      # per model: smoothed latency (ms) + recent failures -> fastest healthy model goes first
        self._static()

    def prov(self, name):
        return next(p for p in self.cfg["providers"] if p["name"] == name)

    def key(self, p):
        return os.environ.get(p.get("key_env", ""), "").strip()

    def _static(self):
        keep = [e for e in self.entries if e.get("found")]
        self.entries = [{"provider": p["name"], "model": m, "vision": None}
                        for p in self.cfg["providers"] if self.key(p) for m in p["models"]]
        for e in keep:
            if self.key(self.prov(e["provider"])) and not any(x["model"] == e["model"] and x["provider"] == e["provider"] for x in self.entries):
                self.entries.append(e)

    @property
    def ready(self):
        return bool(self.entries)

    @staticmethod
    def _k(e, v=False):
        return ("v|" if v else "") + f'{e["provider"]}|{e["model"]}'

    async def refresh(self):
        self._static()
        seen = {(e["provider"], e["model"]) for e in self.entries}
        async with httpx.AsyncClient(timeout=20) as c:
            for p in self.cfg["providers"]:
                if not (self.key(p) and p.get("discover_free")):
                    continue
                try:
                    r = await c.get(p["base"].rstrip("/") + "/models", headers={"Authorization": "Bearer " + self.key(p)})
                    data = r.json().get("data", []) if r.status_code == 200 else []
                except Exception:
                    continue
                n = 0
                for m in data:
                    if n >= 30:
                        break
                    if is_free(m):
                        if (p["name"], m["id"]) in seen:
                            for e in self.entries:  # annotate static entries with vision info
                                if (e["provider"], e["model"]) == (p["name"], m["id"]):
                                    e["vision"] = vision_flag(m)
                            continue
                        self.entries.append({"provider": p["name"], "model": m["id"], "vision": vision_flag(m), "found": True})
                        seen.add((p["name"], m["id"]))
                        n += 1

    def _rank(self, e, fast=True):
        st = self.stat.get(self._k(e), {})
        slow = bool(SLOWISH.search(e["model"]))
        ms = st.get("ms", 2500 + (3000 if slow else 0)) + (4000 if (fast and slow) else 0)
        return ms + st.get("fail", 0) * 1500 - (2000 if self._k(e) == self.last else 0)

    def _note(self, e, ok, ms=None):
        st = self.stat.setdefault(self._k(e), {})
        if ok:
            st["ms"] = ms if "ms" not in st else st["ms"] * 0.6 + ms * 0.4
            st["fail"] = max(0, st.get("fail", 0) - 1)
        else:
            st["fail"] = st.get("fail", 0) + 1

    def _order(self, vision=False, fast=True):
        now = time.time()
        pool = [e for e in self.entries if self.cool.get(self._k(e, vision), 0) < now and (not vision or e["vision"] is not False)]
        pool.sort(key=lambda e: self._rank(e, fast))
        if vision:
            pool.sort(key=lambda e: e["vision"] is not True)
        if self.pinned:
            pool.sort(key=lambda e: self._k(e) != self.pinned)
        return pool

    def catalog(self):
        now = time.time()
        return [{"provider": e["provider"], "model": e["model"], "vision": e["vision"], "id": self._k(e),
                 "cooling": max(0, int(self.cool.get(self._k(e), 0) - now)), "pinned": self._k(e) == self.pinned,
                 "ms": int(self.stat.get(self._k(e), {}).get("ms", 0))}
                for e in self.entries]

    async def _one(self, c, e, messages, max_tokens, temperature, on_delta, first_tok):
        """One streamed request. A dead or slow model is detected after `first_tok` seconds, not after a full timeout."""
        p = self.prov(e["provider"])
        t0 = time.time()
        out, got = [], False
        async with c.stream("POST", p["base"].rstrip("/") + "/chat/completions",
                            headers={"Authorization": "Bearer " + self.key(p), "X-Title": "Son of Anton", "HTTP-Referer": "http://localhost"},
                            json={"model": e["model"], "messages": messages, "max_tokens": max_tokens,
                                  "temperature": temperature, "stream": True}) as r:
            if r.status_code != 200:
                await r.aread()
                raise _HTTP(r.status_code, r.headers.get("retry-after"))
            if "text/event-stream" not in r.headers.get("content-type", ""):
                j = json.loads((await r.aread()) or b"{}")
                txt = ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                if on_delta and txt:
                    on_delta(txt)
                return strip_think(txt), int((time.time() - t0) * 1000)
            it = r.aiter_lines().__aiter__()
            while True:
                try:
                    line = await asyncio.wait_for(it.__anext__(), first_tok if not got else 25)
                except StopAsyncIteration:
                    break
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    d = ((json.loads(data).get("choices") or [{}])[0].get("delta")) or {}
                except Exception:
                    continue
                piece = d.get("content") or ""
                if piece or d.get("reasoning_content") or d.get("reasoning"):
                    got = True
                if piece:
                    out.append(piece)
                    if on_delta:
                        on_delta(piece)
        return strip_think("".join(out)), int((time.time() - t0) * 1000)

    async def chat(self, messages, max_tokens=900, temperature=0.4, vision=False, fast=True, on_delta=None, max_attempts=4, timeout=None):
        cands = self._order(vision, fast)
        if not cands:
            raise RuntimeError("no cloud model available" + (" with vision" if vision else "") + " (add a key in the dashboard, or wait for cooldown)")
        per = timeout or (80 if vision else 60)
        err, tried, net_err = None, 0, 0
        deadline = time.time() + (timeout * 2 if timeout else (80 if vision else 50))
        tmo = httpx.Timeout(connect=8, read=15, write=20, pool=5)
        async with httpx.AsyncClient(timeout=tmo) as c:
            for e in cands:
                if tried >= max_attempts or time.time() > deadline:
                    break
                tried += 1
                ck = self._k(e, vision)
                try:
                    txt, ms = await asyncio.wait_for(self._one(c, e, messages, max_tokens, temperature, on_delta, 20 if vision else 9), per)
                    if txt:
                        self.last = self._k(e)
                        self._note(e, True, ms)
                        return txt, e
                    err = f'{e["model"]}: empty reply'
                    self.cool[ck] = time.time() + 30
                    self._note(e, False)
                except _HTTP as h:
                    err = f'{e["model"]} HTTP {h.code}'
                    try:
                        wait = min(300, int(h.retry)) if h.retry else 0
                    except ValueError:
                        wait = 0
                    self.cool[ck] = time.time() + (3600 if h.code in (401, 403, 404) else max(wait, 90) if h.code == 429 else 60)
                    self._note(e, False)
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as ex:
                    net_err += 1
                    err = f"{type(ex).__name__}"
                    if net_err >= 2:                                   # two providers unreachable in a row = we're offline
                        raise RuntimeError(f"offline ({type(ex).__name__})")
                except Exception as ex:
                    err = f'{e["model"]}: {type(ex).__name__}'
                    self.cool[ck] = time.time() + 120
                    self._note(e, False)
        if net_err and not tried - net_err:
            raise RuntimeError(f"offline ({err})")
        raise RuntimeError("all cloud models failed (" + str(err) + ")")

    async def vision(self, question, b64_jpeg):
        msgs = [{"role": "user", "content": [{"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64_jpeg}}]}]
        txt, e = await self.chat(msgs, max_tokens=600, temperature=0.2, vision=True)
        return txt

    async def test(self):
        """Diagnostics: per provider, key present? /models reachable? tiny chat works?"""
        out = []
        async with httpx.AsyncClient(timeout=25) as c:
            for p in self.cfg["providers"]:
                if not self.key(p):
                    out.append(f'{p["name"]}: no key set')
                    continue
                h = {"Authorization": "Bearer " + self.key(p)}
                try:
                    r = await c.get(p["base"].rstrip("/") + "/models", headers=h)
                    line = f'{p["name"]}: /models HTTP {r.status_code}'
                    if r.status_code in (401, 403):
                        out.append(line + "  ← key rejected, re-enter it")
                        continue
                    r = await c.post(p["base"].rstrip("/") + "/chat/completions", headers=h,
                                     json={"model": p["models"][0], "messages": [{"role": "user", "content": "say ok"}], "max_tokens": 5})
                    line += f' · chat({p["models"][0]}) HTTP {r.status_code}'
                    out.append(line + ("  ✅" if r.status_code == 200 else "  " + r.text[:120]))
                except Exception as ex:
                    out.append(f'{p["name"]}: unreachable ({type(ex).__name__}) - check internet')
        return out


def _ollama():
    p = shutil.which("ollama")
    if p:
        return p
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
        c = os.path.join(base, "Programs", "Ollama", "ollama.exe") if base else ""
        if c and os.path.exists(c):
            return c
    return None


class Local:
    """Small local model via Ollama. Self-heals: starts ollama, pulls the model, rechecks, tolerates hiccups."""
    def __init__(self, cfg):
        self.c = cfg["local"]
        self.model = self.c["model"]
        self.ok, self.fails, self.status = False, 0, "starting"
        self.err = None
        self._pull = None

    async def _tags(self):
        async with httpx.AsyncClient(timeout=5) as cl:
            r = await cl.get(self.c["url"] + "/api/tags")
            return [m["name"] for m in r.json().get("models", [])]

    async def check(self):
        if not self.c["enabled"]:
            self.status = "disabled"
            return False
        try:
            names = await self._tags()
        except Exception:
            if _ollama():
                self.status = "starting ollama"
                kw = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
                subprocess.Popen([_ollama(), "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
                for _ in range(10):
                    await asyncio.sleep(1)
                    try:
                        names = await self._tags()
                        break
                    except Exception:
                        names = None
                if names is None:
                    self.ok, self.status = False, "ollama won't start"
                    return False
            else:
                self.ok, self.status = False, "ollama not installed"
                return False
        want = self.c["model"]
        hit = next((n for n in names if n == want or n.split(":")[0] == want.split(":")[0] and n.startswith(want)), None) \
            or next((n for n in names if n.startswith(want.split(":")[0])), None) \
            or next((n for n in names if re.search(r"qwen|llama3\.2|gemma|phi|smollm", n)), None)
        if hit:
            self.model, self.ok, self.fails, self.status = hit, True, 0, "ready"
            return True
        self.ok = False
        if self._pull is None or self._pull.poll() is not None:
            self.status = f"pulling {want}"
            self._pull = subprocess.Popen([_ollama(), "pull", want], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False

    async def chat(self, messages, max_tokens=120):
        async with httpx.AsyncClient(timeout=35) as cl:
            r = await cl.post(self.c["url"] + "/api/chat", json={
                "model": self.model, "messages": messages, "stream": False, "keep_alive": self.c["keep_alive"],
                "options": {"num_predict": max_tokens, "temperature": 0.7, "num_ctx": 2048}})
            j = r.json()
            if r.status_code != 200 or "message" not in j:
                self.err = str(j.get("error") or f"HTTP {r.status_code}")[:160]
                raise RuntimeError(self.err)
            txt = strip_think(j["message"]["content"])
            self.fails, self.err = 0, None
            return txt

    def failed(self):
        self.fails += 1
        if self.fails >= 3:
            self.ok, self.status = False, "failing, rechecking"

    async def warm(self):
        try:
            await self.chat([{"role": "user", "content": "hi"}], 2)
        except Exception:
            pass

    async def keepalive(self):
        while True:
            await asyncio.sleep(120 if self.ok else 20)
            was = self.ok
            await self.check()
            if self.ok and not was:
                await self.warm()
