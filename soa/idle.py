import asyncio, platform, re, subprocess, time
from . import tools

SYS = platform.system()
_pos = {"p": None, "t": time.time()}


def get_idle_seconds():
    try:
        if SYS == "Windows":
            import ctypes

            class LII(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            li = LII()
            li.cbSize = ctypes.sizeof(li)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
            return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0
        if SYS == "Darwin":
            out = subprocess.check_output(["ioreg", "-c", "IOHIDSystem"], text=True, timeout=3)
            return int(re.search(r'"HIDIdleTime" = (\d+)', out).group(1)) / 1e9
        return int(subprocess.check_output(["xprintidle"], text=True, timeout=2)) / 1000.0
    except Exception:
        try:
            p = tuple(tools._pg().position())
            if p != _pos["p"]:
                _pos["p"], _pos["t"] = p, time.time()
            return time.time() - _pos["t"]
        except Exception:
            return 0.0


CONSOLIDATE = """Below is a recent conversation between a user and their PC assistant.
Extract up to 5 durable facts about the USER (preferences, projects, habits, names, goals). Skip trivia and anything about the assistant.
Reply ONLY with a JSON list of short strings, e.g. ["likes lofi while coding"]. If nothing durable, reply [].

{convo}"""

SKILL = """You are improving a PC assistant by writing ONE new small, useful, SAFE Python skill.
Existing tools:
{tools}
What the user often asks for: {habits}
Known about the user: {facts}
Write a skill that does NOT duplicate existing tools. Rules: standard library + httpx/psutil only; no subprocess, no deleting/renaming files,
no eval/exec; return a short plain-text string; handle errors; keep it under 40 lines.
Reply in exactly this format:
NAME: short_snake_case_name
```python
NAME = "short_snake_case_name"
DESCRIPTION = "what it does"
ARGS = {{"arg": "meaning"}}   # {{}} if none

def run(**kwargs):
    ...
```"""

STUDY_PICK = "Known about the user: {facts}\nPick ONE concrete topic worth researching to be a better assistant to this user. Reply with the search query only (max 8 words)."
STUDY_SUM = "Summarize the key useful points about '{q}' in 3 short bullets for a personal assistant's notes.\n\n{text}"


class SelfImprover:
    JOBS = ["consolidate", "habits", "reflect", "skill", "study"]

    def __init__(self, cfg, store, cloud, brain, bus):
        self.cfg, self.store, self.cloud, self.brain, self.bus = cfg, store, cloud, brain, bus
        self.i = 0
        self.last = 0.0
        self.idle = 0.0
        self.running = None

    def still_idle(self):
        return get_idle_seconds() >= self.cfg["idle_seconds"] and not self.brain.busy

    async def loop(self):
        si = self.cfg["self_improve"]
        while True:
            await asyncio.sleep(15)
            self.idle = await asyncio.get_running_loop().run_in_executor(None, get_idle_seconds)
            self.bus.emit("idle", seconds=int(self.idle), improving=self.running)
            if not si["enabled"] or self.idle < self.cfg["idle_seconds"] or self.brain.busy:
                continue
            if time.time() - self.last < si["cooldown_seconds"] or self.store.cycles_today() >= si["max_cycles_per_day"]:
                continue
            self.last = time.time()
            job = self.JOBS[self.i % len(self.JOBS)]
            self.i += 1
            if job != "habits" and not self.cloud.ready:
                continue
            self.running = job
            self.bus.emit("improve", job=job, status="start")
            try:
                res = await getattr(self, "job_" + job)()
            except Exception as e:
                res = f"failed: {e}"
            self.running = None
            self.store.add_memory("cycle", f"{time.strftime('%H:%M')} {job}: {res}")
            self.bus.emit("improve", job=job, status="done", result=res)

    async def job_habits(self):
        top = [p for p in self.store.top_phrases(8) if p["count"] >= 3]
        if top:
            self.store.add_memory("habit", "Often says: " + ", ".join(f'"{p["phrase"]}" x{p["count"]}' for p in top))
        return f"{len(top)} frequent phrases catalogued"

    async def job_consolidate(self):
        convo = "\n".join(f'{m["role"]}: {m["text"][:200]}' for m in self.store.recent(40))
        if len(convo) < 80:
            return "not enough conversation yet"
        txt, _ = await self.cloud.chat([{"role": "user", "content": CONSOLIDATE.replace("{convo}", convo)}], 300, 0.1)
        import json
        m = re.search(r"\[.*\]", txt, re.S)
        facts = json.loads(m.group(0)) if m else []
        n = sum(self.store.add_memory("fact", str(f)) for f in facts[:5])
        return f"{n} new facts learned"

    async def job_reflect(self):
        traces = [m["text"] for m in self.store.memories("trace", 8)]
        if not traces:
            return "no mistakes to learn from"
        p = ("Tool failures from an assistant:\n" + "\n".join(traces) +
             '\nWrite up to 3 short, general lessons so it avoids these mistakes. Reply ONLY with a JSON list of strings.')
        txt, _ = await self.cloud.chat([{"role": "user", "content": p}], 250, 0.2)
        import json
        m = re.search(r"\[.*\]", txt, re.S)
        n = sum(self.store.add_memory("lesson", str(x)) for x in (json.loads(m.group(0)) if m else [])[:3])
        self.store.q("DELETE FROM memory WHERE kind='trace'", (), True)
        return f"{n} lessons learned"

    async def job_skill(self):
        habits = "; ".join(p["phrase"] for p in self.store.top_phrases(6)) or "unknown"
        facts = "; ".join(m["text"] for m in self.store.memories("fact", 6)) or "unknown"
        prompt = SKILL.replace("{tools}", tools.describe()).replace("{habits}", habits).replace("{facts}", facts).replace("{{", "{").replace("}}", "}")
        txt, _ = await self.cloud.chat([{"role": "user", "content": prompt}], 700, 0.5)
        m = re.search(r"```(?:python)?\s*(.*?)```", txt, re.S)
        if not m:
            return "no code produced"
        code = m.group(1)
        nm = re.search(r'NAME\s*=\s*["\'](\w+)', code)
        name, err = tools.save_skill(nm.group(1) if nm else "auto", code)
        return f"learned {name}" if name else f"skill rejected ({err})"

    async def job_study(self):
        facts = "; ".join(m["text"] for m in self.store.memories("fact", 6)) or "a developer"
        q, _ = await self.cloud.chat([{"role": "user", "content": STUDY_PICK.replace("{facts}", facts)}], 40, 0.7)
        q = q.strip().strip('"')[:80]
        loop = asyncio.get_running_loop()
        found = await loop.run_in_executor(None, tools.web_search, q)
        if not self.still_idle():
            return "user came back, paused"
        txt, _ = await self.cloud.chat([{"role": "user", "content": STUDY_SUM.replace("{q}", q).replace("{text}", found[:2500])}], 250, 0.3)
        self.store.add_memory("note", f"{q}: {txt.strip()[:500]}")
        return f"studied '{q}'"
