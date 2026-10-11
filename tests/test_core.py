"""Run: python tests/test_core.py   (no network or keys needed)"""
import asyncio, json, os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from soa import config, tools
from soa.store import Store
from soa.fastpath import FastPath
from soa.wake import Wake
from soa.bus import Bus
from soa.agent import Agent, parse
from soa.brain import Brain

cfg = config.load()
st = Store(Path(tempfile.mkdtemp()) / "t.db")
tools.CTX.update(store=st, cfg=cfg)

# wake word
w = Wake(cfg)
assert w.feed("a", "hello") == (None, None)
assert w.feed("a", "sun of anton")[0] == "wake"
assert w.feed("a", "what time is it over") == ("message", "what time is it")
assert w.feed("b", "son of anton open chrome over") == ("message", "open chrome")

# wake variants (speech engines write "San Antonio")
w2 = Wake(cfg)
assert w2.feed("c", "San Antonio")[0] == "wake"
assert w2.feed("c", "open notepad over") == ("message", "open notepad")
assert w2.feed("d", "Anton good morning over") == ("message", "good morning")
assert w2.feed("e", "I told anthony hello") == (None, None)
w3 = Wake(cfg); w3.feed("f", "anton what time is it"); assert w3.flush("f") == "what time is it"

# bare "son/sun/san" and "anton" call the assistant
from soa.wake import find_wake
assert find_wake("san open chrome over") and find_wake("Sun, what time is it") and find_wake("hey son tell me a joke")
assert find_wake("my son is home") is None and find_wake("son of a gun that hurts") is None

# routing: chat stays local, commands go to the agent
from soa.brain import Brain as _B
_b = _B.__new__(_B)
assert not _b.is_task("how are you doing") and not _b.is_task("tell me a joke") and not _b.is_task("I want to start learning guitar")
assert _b.is_task("open chrome") and _b.is_task("can you play some lofi") and _b.is_task("what's the weather in Nairobi")

# tools: tolerant args, calc, python execution, many tools registered
assert len(tools.TOOLS) >= 55
assert tools.call("calc", {"expression": "2^10 + sqrt(16)"}) == "1028.0"
assert tools.call("calc", {"x": "3x4"}) == "12"
assert tools.call("execute_code", {"code": "print(6*7)"}).strip() == "42"

# updater version compare
from soa import updater
assert updater._v("1.2.0") > updater._v("1.1.9") and not updater._v("1.1.0") > updater._v("1.1.0")

# fast path: seeds + learning
f = FastPath(st, cfg)
assert "Morning" in f.match("Good morning!") or "morning" in f.match("Good morning!").lower()
assert f.match("what's up bro") is None
for _ in range(3):
    f.seen("what's up bro")
f.learn("what's up bro", "Not much, you?")
assert f.match("whats up bro") == "Not much, you?"
f.add_hard("fire it up", "Engines hot.")
assert f.match("fire it up") == "Engines hot."

# skills safety
assert tools.validate_skill("import subprocess\nNAME='a'\nDESCRIPTION='b'\ndef run(**k): pass")
good = "NAME='hello'\nDESCRIPTION='says hi'\nARGS={}\ndef run(**k):\n    return 'hi'"
t, err = tools.save_skill("hello_test", good)
assert t == "skill_hello" and tools.call(t, {}) == "hi", err
(config.DATA / "skills" / "hello_test.py").unlink()

# agent loop with fake cloud
class FakeCloud:
    ready = True
    def __init__(s): s.n = 0
    async def chat(s, m, max_tokens=0, temperature=0, **k):
        s.n += 1
        return ('{"tool":"get_time","args":{}}' if s.n == 1 else '{"final":"Done, boss."}'), {"model": "fake"}
bus = Bus()
ag = Agent(cfg, st, FakeCloud(), bus)
assert asyncio.run(ag.run("what time")) == "Done, boss."
assert parse("```json\n{\"final\":\"x\"}\n```") == {"final": "x"}

# brain routing
class NoLocal: ok = False
b = Brain(cfg, st, FakeCloud(), NoLocal(), bus)
assert asyncio.run(b.handle("good morning", "t")) and b.stats["instant"] == 1
# offline: cloud dead, local alive -> still answers (chat and task paths)
class DeadCloud:
    ready = True
    async def chat(s, *a, **k): raise RuntimeError("all cloud models failed")
class LiveLocal:
    ok, status = True, "ready"
    async def chat(s, m, max_tokens=0): return "Offline but here."
    def failed(s): pass
def _offline_weather(city=""): raise RuntimeError("offline")
tools.TOOLS["weather"]["fn"] = _offline_weather      # emulate no internet
b2 = Brain(cfg, st, DeadCloud(), LiveLocal(), bus)
assert "Offline but here." in asyncio.run(b2.handle("tell me something interesting about owls", "t"))
assert "Offline but here." in asyncio.run(b2.handle("what is the weather like in paris today", "t"))
st.q("DELETE FROM convo", (), True); assert st.recent(5) == []

# ---- v1.5: instant intents run with no model, risky ones are guarded ----
from soa import browser, intents, toolbox
assert intents.match("turn the volume up")[0] == "volume" and intents.match("set a timer for 5 minutes")[1]["seconds"] == 300
assert intents.match("what is the capital of france") is None and intents.match("tell me a joke") is None
ran = []
tools.TOOLS["volume"]["fn"] = lambda action, level=50: ran.append(action) or "ok"
bi = Brain(cfg, st, DeadCloud(), LiveLocal(), bus)
assert asyncio.run(bi.handle("hey turn it up", "t")) == "Louder." and ran == ["up"]          # no model was called (DeadCloud would raise)
assert asyncio.run(bi._instant("type of music do you like")) is None                         # a question, not "type this"
assert asyncio.run(bi._instant("open xyzzyqq")) is None                                      # unknown app falls through to the agent

# ---- v1.5: only the tools a task needs are sent to the model ----
full, rest = toolbox.prompt_for("what's the weather")
full2, _ = toolbox.prompt_for("log in to amazon and buy a charger")
assert "browser_click" not in full and "browser_click" in rest and "browser_click(" in full2
assert len(full) < len(tools.describe()) * 0.6

# ---- v1.5: cloud client streams, ranks by speed, and survives a 429 (local fake provider) ----
import copy
from aiohttp import web as _w
from soa.llm import Cloud
c0 = Cloud(cfg)
c0.entries = [{"provider": "groq", "model": "big-reasoning-120b", "vision": None}, {"provider": "groq", "model": "llama-fast", "vision": None}]
assert c0._order()[0]["model"] == "llama-fast"

async def _provider_test():
    async def comp(req):
        j = await req.json()
        if j["model"] == "bad-model":
            return _w.Response(status=429, headers={"Retry-After": "30"})
        r = _w.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await r.prepare(req)
        for piece in ("<think>hmm</think>He", "llo ", "there"):
            await r.write(('data: {"choices":[{"delta":{"content":%s}}]}\n\n' % json.dumps(piece)).encode())
        await r.write(b"data: [DONE]\n\n")
        return r
    app = _w.Application(); app.router.add_post("/v1/chat/completions", comp)
    run = _w.AppRunner(app); await run.setup()
    site = _w.TCPSite(run, "127.0.0.1", 0); await site.start()
    port = site._server.sockets[0].getsockname()[1]
    c2 = copy.deepcopy(cfg)
    c2["providers"] = [{"name": "fake", "base": f"http://127.0.0.1:{port}/v1", "key_env": "FAKE_KEY", "models": ["bad-model", "good-model"]}]
    os.environ["FAKE_KEY"] = "k"
    cl, got = Cloud(c2), []
    txt, e = await cl.chat([{"role": "user", "content": "hi"}], on_delta=got.append, timeout=30)
    await run.cleanup()
    return txt, e, got, cl
_txt, _e, _got, _cl = asyncio.run(_provider_test())
assert _txt == "Hello there" and _e["model"] == "good-model" and len(_got) >= 2
assert _cl.cool.get("fake|bad-model", 0) > time.time() + 20          # the 429 benched that model, not the whole provider

# ---- v1.5: browser tools are registered ----
from soa import browser
assert all(n in tools.TOOLS for n in ("browser_open", "browser_click", "browser_type", "browser_vision"))
print("ALL TESTS PASSED")
