import asyncio, re, shutil, time
from . import intents, tools
from .agent import Agent
from .fastpath import FastPath

# A request is a TASK only when it is phrased as a command / needs live info. Casual chat stays on the fast local model.
VERBS = (r"open|close|launch|start|search|google|look ?up|find|type|click|press|run|play|pause|resume|mute|unmute|turn|set|take|show|list|"
         r"read|write|create|make|delete|remove|download|install|send|check|copy|paste|scroll|lock|kill|stop|remind|translate|summari[sz]e|"
         r"remember|calculate|organi[sz]e|move|rename|build|fix|debug|generate|draw|screenshot|give me|get me|bring up|switch|go to|"
         r"drag|focus|minimi[sz]e|maximi[sz]e|schedule|search for|whats on|what'?s on|look at")
IMPERATIVE = re.compile(r"^(?:(?:hey|ok|okay|please|can you|could you|would you|will you|go ahead and|now|just|and|then|also)[,\s]+)*(?:" + VERBS + r")\b", re.I)
STRONG = re.compile(r"\b(weather|news|headlines|price of|stock|screenshot|on my screen|my screen|volume|clipboard|my files|my folder|remind me|timer|alarm|"
                    r"youtube|download|install|what do you see|look at (my|the) screen|search (for|the web)|google)\b", re.I)
LOOKUP = re.compile(r"\b(who (is|was|won)|what (is|are|was) the (latest|current|capital|population|price|score)|when (is|was|did)|where is|how (many|much)|"
                    r"latest|current|today|tonight|tomorrow|news|score|weather|price|define|meaning of|population|capital of|release date)\b", re.I)

PERSONA = ("You are Son of Anton, a sharp, dry-witted, loyal AI sidekick living on the user's PC, like Jarvis. "
           "Talk like a real person: casual, 1-2 short sentences, no lists, no emojis, never say 'as an AI'. Never invent facts. "
           "Chat naturally about anything conversational, opinions, advice and general knowledge. ONLY if the user clearly wants an action on "
           "the computer, a live lookup (news, weather, prices, scores), or exact maths/code, reply with exactly the single word: ESCALATE")
CHAT_ONLY = ("You are Son of Anton, a sharp, dry-witted, loyal AI sidekick living on the user's PC, like Jarvis. Talk like a real person: "
             "casual, 1-2 short sentences, no lists, no emojis, never say 'as an AI'. Answer the user directly, never refuse to chat.")


OFFLINE = (" You are currently OFFLINE: the internet and cloud models are unreachable, so you can't do heavy tasks, look things up or use "
           "current info right now. Answer briefly from what you know; if it needs internet, say so honestly in one sentence.")


def _known_app(name):
    n = name.lower().strip()
    if tools.SYS == "Darwin" or n in tools.APPS or shutil.which(n):
        return True
    return tools.SYS == "Windows" and bool(tools._find_lnk(n))


class Brain:
    def __init__(self, cfg, store, cloud, local, bus):
        self.cfg, self.store, self.cloud, self.local, self.bus = cfg, store, cloud, local, bus
        self.fast = FastPath(store, cfg)
        self.agent = Agent(cfg, store, cloud, bus)
        self.busy = 0
        self._lc = 0
        self._down = 0.0
        self.stats = {"instant": 0, "local": 0, "cloud": 0, "agent": 0, "ms": []}

    def is_task(self, text):
        t = text.strip()
        return len(t.split()) > 28 or bool(IMPERATIVE.search(t)) or bool(STRONG.search(t))

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
                reply = await self._instant(text)        # common PC commands: no model call, nothing uploaded
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

    async def _instant(self, text):
        hit = intents.match(text)
        if not hit:
            return None
        name, args, tpl = hit
        if name == "open_app" and not _known_app(args.get("name", "")):
            return None
        if name == "type_text" and text.strip().lower().split()[1:2] in (["of"], ["a"], ["an"], ["the"], ["your"], ["my"], ["is"], ["do"]):
            return None                                  # "type of music do you like" is a question, not a command
        self.bus.emit("step", n=1, tool=name, args=args, model="instant")
        res = await asyncio.get_running_loop().run_in_executor(None, tools.call, name, args)
        self.bus.emit("step_result", tool=name, result=res[:300])
        if res.startswith(("error", "refused")):
            return None                                  # let the agent try
        if tpl == "NEWS":
            return intents.speak_result("news", res)
        return tpl.replace("{r}", intents.speak_result(name, res)) if "{r}" in tpl else tpl

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

    def _lfail(self, e):
        try:
            self.local.err = f"{type(e).__name__}: {e}"[:160]
        except Exception:
            pass
        self.local.failed()

    def _why(self):
        e = getattr(self.local, "err", None)
        return f" (local error: {e})" if e else ""

    async def _offline(self, text):
        """Cloud/internet unavailable: answer with the local model, honestly."""
        if not await self._ensure_local():
            return None
        try:
            msgs = [{"role": "system", "content": PERSONA.split(" If the user")[0] + OFFLINE + self._facts()}] + self._hist()
            return (await self.local.chat(msgs)) or None
        except Exception as e:
            self._lfail(e)
            return None

    async def _agent(self, text, src):
        self.bus.emit("ack", to=src, text="On it.")
        try:
            return await self.agent.run(text, src), "agent"
        except Exception:
            self._down = time.time() + 30
            r = await self._offline(text)
            if r:
                return "Offline, so no heavy lifting right now. " + r, "local"
            raise

    async def _chat(self, text, src):
        if self.cloud.ready and time.time() >= self._down and (LOOKUP.search(text) or len(text.split()) > 14):
            try:                                          # knowledge-heavy: skip the small local model, go straight to the cloud
                return await self._cloud_chat(text)
            except Exception:
                self._down = time.time() + 30
        if time.time() < self._down:          # internet known to be down: don't bother escalating to the cloud
            r = await self._offline(text)
            if r:
                return r, "local"
        if await self._ensure_local():
            try:
                msgs = [{"role": "system", "content": PERSONA + self._facts()}] + self._hist()
                r = await self.local.chat(msgs)
                if r and r.upper().startswith("ESCALATE") and not LOOKUP.search(text):
                    msgs[0]["content"] = CHAT_ONLY + self._facts()      # small models over-escalate: answer it locally
                    r = await self.local.chat(msgs)
                if r and not r.upper().startswith("ESCALATE"):
                    self.fast.learn(text, r)
                    return r, "local"
            except Exception as e:
                self._lfail(e)
            if self.cloud.ready:
                try:
                    return await self._cloud_chat(text)
                except Exception:
                    self._down = time.time() + 30
            r = await self._offline(text)
            if r:
                return r, "local"
            return "I'm offline and my local brain couldn't answer" + self._why() + ". Try again in a moment.", "error"
        if self.cloud.ready:
            try:
                return await self._cloud_chat(text)
            except Exception:
                self._down = time.time() + 30
                return f"I'm offline and my local brain isn't ready yet ({getattr(self.local, 'status', '?')}). Give it a minute or reconnect.", "error"
        return "I've got no brain online yet. Add an API key in the dashboard, or let the local brain finish setting up.", "error"

    async def _cloud_chat(self, text):
        msgs = [{"role": "system", "content": PERSONA.split(" If the user")[0] + self._facts()}] + self._hist()
        r, _ = await self.cloud.chat(msgs, max_tokens=150, temperature=0.7)
        return r, "cloud"
