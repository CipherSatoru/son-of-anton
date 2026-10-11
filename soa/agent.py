import asyncio, json, re
from . import toolbox, tools

SYSTEM = """You are Anton, a fast PC agent. Reply with ONE JSON object, nothing else:
{"tool":"name","args":{...}} | {"steps":[{"tool":..,"args":..},..]} (independent calls batched, max 4) | {"final":"1-2 short spoken sentences"}
Use the fewest steps. Batch independent calls. Never repeat a call. Don't explain. If a tool errors, adapt once.
TOOLS:
{tools}
OTHER (call by name if needed): {rest}{extra}"""


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


def _compact(obj):
    if "steps" in obj:
        return json.dumps({"steps": [{"tool": c.get("tool"), "args": c.get("args") or {}} for c in obj["steps"][:4]]}, separators=(",", ":"))
    return json.dumps({"tool": obj.get("tool"), "args": obj.get("args") or {}}, separators=(",", ":"))


class Agent:
    def __init__(self, cfg, store, cloud, bus):
        self.cfg, self.store, self.cloud, self.bus = cfg, store, cloud, bus

    def system_for(self, task):
        block, rest = toolbox.prompt_for(task)
        facts = "; ".join(m["text"] for m in self.store.search_memory(task, 5))
        lessons = "; ".join(m["text"] for m in self.store.memories("lesson", 4))
        extra = (f"\nUSER FACTS: {facts}" if facts else "") + (f"\nLESSONS: {lessons}" if lessons else "")
        return SYSTEM.replace("{tools}", block).replace("{rest}", rest).replace("{extra}", extra)

    async def _exec(self, calls, step):
        loop, out = asyncio.get_running_loop(), []
        for c in calls[:4]:
            name, args = c.get("tool"), c.get("args") or {}
            if not name:
                continue
            self.bus.emit("step", n=step + 1, tool=name, args=args, model=getattr(self.cloud, "last", "") or "")
            res = await loop.run_in_executor(None, tools.call, name, args)
            self.bus.emit("step_result", tool=name, result=res[:300])
            if res.startswith(("error", "refused")):
                self.store.add_memory("trace", f"{name}{json.dumps(args)[:100]} -> {res[:150]}")
            out.append(f"{name}: {res[:800]}")
        return out

    async def run(self, task, src="?"):
        convo = [{"role": "system", "content": self.system_for(task)}]
        for m in self.store.recent(5)[:-1][-4:]:
            convo.append({"role": "user" if m["role"] == "user" else "assistant", "content": m["text"][:140]})
        convo.append({"role": "user", "content": task})
        last = None
        for step in range(self.cfg["agent_max_steps"]):
            txt, used = await self.cloud.chat(convo, max_tokens=320, temperature=0.1, timeout=30)
            obj = parse(txt)
            calls = obj.get("steps") if isinstance(obj.get("steps"), list) else ([obj] if obj.get("tool") else [])
            if not calls:
                return str(obj.get("final") or txt).strip()[:400]
            sig = json.dumps([(c.get("tool"), c.get("args")) for c in calls], sort_keys=True, default=str)
            if sig == last:
                return "I got stuck repeating myself on that one. Try rephrasing?"
            last = sig
            results = await self._exec(calls, step)
            convo.append({"role": "assistant", "content": _compact(obj)})
            convo.append({"role": "user", "content": "RESULT\n" + "\n".join(results)})
            for m in convo[2:-3]:        # old observations shrink: the model already used them
                if m["role"] == "user" and m["content"].startswith("RESULT") and len(m["content"]) > 220:
                    m["content"] = m["content"][:200] + "..."
        return "That took more steps than I'm allowed. I did what I could."
