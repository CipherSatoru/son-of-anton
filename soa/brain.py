import asyncio, re, time
from .agent import Agent
from .fastpath import FastPath

TASK = re.compile(r"\b(open|close|launch|start|search|google|look ?up|find|type|click|press|run|play|pause|mute|unmute|volume|"
                  r"screenshot|remind|timer|create|make|write|delete|remove|download|install|send|check|show|list|read|save|"
                  r"copy|paste|scroll|lock|kill|weather|news|price|translate|summari[sz]e|remember|calculate|upgrade|update|"
                  r"look at|on my screen|what do you see|organi[sz]e|move|rename|build|fix|debug)\b", re.I)

PERSONA = ("You are Son of Anton, a sharp, dry-witted, loyal AI sidekick living on the user's PC, like Jarvis. "
           "Talk like a real person: casual, 1-2 short sentences, no lists, no emojis, never say 'as an AI'. Never invent facts. "
           "If the user wants an action on the computer, a lookup, maths, current info, code, or anything you're unsure about, "
           "reply with exactly the single word: ESCALATE")


OFFLINE = (" You are currently OFFLINE: the internet and cloud models are unreachable, so you can't do heavy tasks, look things up or use "
           "current info right now. Answer briefly from what you know; if it needs internet, say so honestly in one sentence.")


class Brain:
    def __init__(self, cfg, store, cloud, local, bus):
        self.cfg, self.store, self.cloud, self.local, self.bus = cfg, store, cloud, local, bus
        self.fast = FastPath(store, cfg)
        self.agent = Agent(cfg, store, cloud, bus)
        self.busy = 0
        self._lc = 0
        self.stats = {"instant": 0, "local": 0, "cloud": 0, "agent": 0, "ms": []}

    def is_task(self, text):
        return len(text.split()) > 14 or bool(TASK.search(text))

    def _facts(self):
        f = [m["text"] for m in self.store.memories("fact", 5)]
        return ("\nKnown about the user: " + "; ".join(f)) if f else ""

    def _hist(self, n=6):
        return [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"][:300]}
                for m in self.store.recent(n)]

    async def handle(self, text, src="dashboard"):
        t0 = time.time()
        self.busy += 1
        route = "instant"
        try:
            self.store.log("user", text, src)
            self.bus.emit("user", who=src, text=text)
            self.fast.seen(text)
            reply = self.fast.match(text)
            if reply is None:
                if self.is_task(text):
                    reply, route = await self._agent(text, src)
                else:
                    reply, route = await self._chat(text, src)
        except Exception as e:
            reply, route = f"Hit a snag: {e}", "error"
        finally:
            self.busy -= 1
        ms = int((time.time() - t0) * 1000)
        self.store.log("assistant", reply, src)
        if route in self.stats:
            self.stats[route] += 1
            self.stats["ms"] = (self.stats["ms"] + [ms])[-50:]
        self.bus.emit("reply", to=src, text=reply, route=route, ms=ms)
        return reply

    async def _ensure_local(self):
        if getattr(self.local, "ok", False):
            return True
        chk = getattr(self.local, "check", None)
        if chk and time.time() - self._lc > 20:
            self._lc = time.time()
            try:
                await asyncio.wait_for(chk(), 20)
            except Exception:
                pass
        return bool(getattr(self.local, "ok", False))

    async def _offline(self, text):
        """Cloud/internet unavailable: answer with the local model, honestly."""
        if not await self._ensure_local():
            return None
        try:
            msgs = [{"role": "system", "content": PERSONA.split(" If the user")[0] + OFFLINE + self._facts()}] + self._hist()
            return (await self.local.chat(msgs)) or None
        except Exception:
            self.local.failed()
            return None

    async def _agent(self, text, src):
        self.bus.emit("ack", to=src, text="On it.")
        try:
            return await self.agent.run(text, src), "agent"
        except Exception:
            r = await self._offline(text)
            if r:
                return "Offline, so no heavy lifting right now. " + r, "local"
            raise

    async def _chat(self, text, src):
        if await self._ensure_local():
            try:
                msgs = [{"role": "system", "content": PERSONA + self._facts()}] + self._hist()
                r = await self.local.chat(msgs)
                if r and not r.upper().startswith("ESCALATE"):
                    self.fast.learn(text, r)
                    return r, "local"
            except Exception:
                self.local.failed()
            if self.cloud.ready:
                try:
                    return await self._cloud_chat(text)
                except Exception:
                    pass
            r = await self._offline(text)
            if r:
                return r, "local"
            return "I'm offline and couldn't work that one out locally. Try again when the internet is back.", "error"
        if self.cloud.ready:
            try:
                return await self._cloud_chat(text)
            except Exception:
                return f"I'm offline and my local brain isn't ready yet ({getattr(self.local, 'status', '?')}). Give it a minute or reconnect.", "error"
        return "I've got no brain online yet. Add an API key in the dashboard, or let the local brain finish setting up.", "error"

    async def _cloud_chat(self, text):
        msgs = [{"role": "system", "content": PERSONA.split(" If the user")[0] + self._facts()}] + self._hist()
        r, _ = await self.cloud.chat(msgs, max_tokens=150, temperature=0.7)
        return r, "cloud"
