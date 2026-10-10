"""Run: python tests/test_core.py   (no network or keys needed)"""
import asyncio, sys, tempfile, time
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
    async def chat(s, m, max_tokens=0, temperature=0):
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
print("ALL TESTS PASSED")
