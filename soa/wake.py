import re, time

WAKE = re.compile(r"\b(?:(?:s[ou]n+|san|sean)\s+(?:of\s+|off\s+|uv\s+)?(?:ant[h]?on(?:io|e)?|and\s*ton)|ant[h]?on(?:io|e)?)\b", re.I)
END = re.compile(r"[\s,.!?]*\bover[\s.!?]*$", re.I)


class Wake:
    """Per-source state machine: idle -> (wake: 'son of anton' / 'anton') -> capture -> ('over') -> message."""
    def __init__(self, cfg):
        self.timeout = cfg["wake_timeout"]
        self.state = {}

    def feed(self, who, text):
        text = (text or "").strip()
        if not text:
            return None, None
        st = self.state.get(who)
        if st and time.time() - st["t"] > self.timeout:
            self.state.pop(who, None)
            st = None
        event = None
        if st is None:
            m = WAKE.search(text)
            if not m or len(text[:m.start()].split()) > 3:
                return None, None
            st = self.state[who] = {"buf": [], "t": time.time()}
            text = text[m.end():].strip(" ,.:;-")
            event = "wake"
        st["t"] = time.time()
        if text:
            if END.search(text):
                text = END.sub("", text).strip()
                if text:
                    st["buf"].append(text)
                msg = " ".join(st["buf"]).strip()
                self.state.pop(who, None)
                return ("message", msg) if msg else (None, None)
            st["buf"].append(text)
        return event, None

    def listening(self, who):
        return who in self.state

    def flush(self, who):
        st = self.state.pop(who, None)
        return " ".join(st["buf"]).strip() if st else ""
