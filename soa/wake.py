import difflib, re, time

# Speech engines mangle "Son of Anton" in many ways ("sun of anthon", "San Antonio", "some of Antoine"...).
# Matching is fuzzy instead of one rigid regex. Add your own misheard variants in config.json:
#   {"wake_aliases": ["antun", "anthem"]}
SON = {"son", "sun", "sonn", "sunn", "san", "sean", "sam", "some", "sawn", "soon", "sonny", "sunny",
       "santa", "sone", "sohn", "sonic", "sin", "sen"}
CONNECT = {"of", "off", "uv", "ov", "a", "the", "from", "have"}
ANTON = {"anton", "antone", "anthon", "anthone", "antoine", "antonio", "antonia", "antoni", "antan", "aunton",
         "onton", "anten", "antin", "untan", "aton", "antun", "antonn", "anthan", "antwan"}
WEAK = {"anthony", "antony"}          # real names: only count at the very start or right after a "son of"
LEAD = {"hey", "hi", "ok", "okay", "yo", "hello"}
END = re.compile(r"[\s,.!?]*\bover[\s.!?]*$", re.I)
TOK = re.compile(r"[A-Za-z0-9']+")


def _r(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def _anton(t, extra):
    return t in ANTON or t in extra or (t not in WEAK and len(t) >= 4 and _r(t, "anton") >= 0.8)


def _son(t):
    return t in SON or (len(t) <= 5 and _r(t, "son") >= 0.8)


def find_wake(text, extra=()):
    """-> (start_char, end_char) of the wake phrase, or None."""
    toks = [(m.group().lower().strip("'"), m.start(), m.end()) for m in TOK.finditer(text)]
    w = [t[0] for t in toks]
    n = len(w)
    for i in range(n):
        t = w[i]
        end = i
        if len(t) >= 8 and (t.startswith("sonof") or _r(t, "sonofanton") >= 0.8):
            return toks[i][1], toks[i][2]
        if _anton(t, extra) or t in WEAK:
            weak = t in WEAK and not _anton(t, extra)
        elif i + 1 < n and len(t) <= 5 and len(w[i + 1]) <= 4 and _anton(t + w[i + 1], extra):
            end, weak = i + 1, False                      # "and ton", "an ton", "aunt on"
        else:
            continue
        s = i
        if i >= 2 and w[i - 1] in CONNECT and _son(w[i - 2]):
            s = i - 2
        elif i >= 1 and _son(w[i - 1]):
            s = i - 1
        if weak and not (s < i or s == 0 or (s == 1 and w[0] in LEAD)):
            continue
        if s > 3:                                          # wake phrase must be near the start of the utterance
            continue
        return toks[s][1], toks[end][2]
    return None


class Wake:
    """Per-source state machine: idle -> (wake: 'son of anton' / 'anton') -> capture -> ('over') -> message."""
    def __init__(self, cfg):
        self.timeout = cfg["wake_timeout"]
        self.extra = {a.lower().strip() for a in cfg.get("wake_aliases", []) if a.strip()}
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
            m = find_wake(text, self.extra)
            if not m:
                return None, None
            st = self.state[who] = {"buf": [], "t": time.time()}
            text = text[m[1]:].strip(" ,.:;-")
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
