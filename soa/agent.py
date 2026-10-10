import asyncio, json, re
from . import tools

SYSTEM = """You are {name}, an autonomous agent running on the user's PC (think Jarvis). Finish the task using tools.
Reply with EXACTLY ONE JSON object, no markdown, no extra text:
  use a tool:  {"thought":"short","tool":"tool_name","args":{"arg":"value"}}
  finished:    {"final":"what to say out loud: 1-3 casual sentences, no lists"}
Rules: one tool per turn; check the result before the next step; never invent results; if a tool errors, adapt or explain.
Prefer the cheapest path (few steps). Ask the user only if truly blocked. For real-world facts use web_search.
TOOLS:
{tools}
LESSONS FROM PAST MISTAKES:
{lessons}
USER MEMORY:
{mem}
"""


def parse(txt):
    txt = re.sub(r"```(?:json)?", "", txt).strip()
    i = txt.find("{")
    if i < 0:
        return {"final": txt}
    try:
        obj, _ = json.JSONDecoder().raw_decode(txt[i:])
        return obj if isinstance(obj, dict) else {"final": txt}
    except Exception:
        return {"final": txt}


class Agent:
    def __init__(self, cfg, store, cloud, bus):
        self.cfg, self.store, self.cloud, self.bus = cfg, store, cloud, bus

    async def run(self, task, src="?"):
        mem = "\n".join("- " + m["text"] for m in self.store.search_memory(task, 8)) or "(none)"
        lessons = "\n".join("- " + m["text"] for m in self.store.memories("lesson", 6)) or "(none yet)"
        sysmsg = SYSTEM.replace("{name}", self.cfg["name"]).replace("{tools}", tools.describe()).replace("{mem}", mem).replace("{lessons}", lessons)
        convo = [{"role": "system", "content": sysmsg}]
        for m in self.store.recent(6)[:-1]:
            convo.append({"role": "user" if m["role"] == "user" else "assistant", "content": m["text"][:300]})
        convo.append({"role": "user", "content": task})
        last, loops = None, 0
        for step in range(self.cfg["agent_max_steps"]):
            txt, used = await self.cloud.chat(convo, max_tokens=700, temperature=0.2)
            obj = parse(txt)
            if "final" in obj and "tool" not in obj:
                return str(obj["final"]).strip()
            name, args = obj.get("tool"), obj.get("args") or {}
            if not name:
                return txt.strip()
            sig = (name, json.dumps(args, sort_keys=True))
            loops = loops + 1 if sig == last else 0
            last = sig
            if loops >= 2:
                return "I got stuck repeating myself on that one. Try rephrasing?"
            self.bus.emit("step", n=step + 1, tool=name, args=args, model=used["model"])
            res = await asyncio.get_running_loop().run_in_executor(None, tools.call, name, args)
            self.bus.emit("step_result", tool=name, result=res[:300])
            if res.startswith(("error", "refused")):
                self.store.add_memory("trace", f"{name}{json.dumps(args)[:100]} -> {res[:150]}")
            convo.append({"role": "assistant", "content": json.dumps(obj)})
            convo.append({"role": "user", "content": f"TOOL RESULT ({name}): {res[:1500]}"})
        return "That took more steps than I'm allowed. I did what I could."
