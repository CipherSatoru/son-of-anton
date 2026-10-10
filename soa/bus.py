import asyncio, time
from collections import deque


class Bus:
    """Tiny pub/sub; emit() is safe from any thread."""
    def __init__(self):
        self.subs = set()
        self.log = deque(maxlen=200)
        self.loop = None

    def emit(self, type, **kw):
        ev = {"type": type, "ts": time.time(), **kw}
        if type != "idle":
            self.log.append(ev)
        if self.loop:
            self.loop.call_soon_threadsafe(self._push, ev)

    def _push(self, ev):
        for q in list(self.subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass
