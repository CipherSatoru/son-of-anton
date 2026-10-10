import difflib, random, re, time


def norm(t):
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", t.lower()).split())


def _pick(*xs):
    fn = lambda: random.choice(xs)
    fn.opts = xs
    return fn


def _time():
    return time.strftime("It's %I:%M %p.").replace("It's 0", "It's ")


def _date():
    return time.strftime("It's %A, %d %B.")


SEEDS = [
    (r"(good )?morning( anton)?", _pick("Morning. Systems are up, coffee is your department.",
                                         "Morning, boss. What are we breaking today?", "Good morning. Ready when you are.")),
    (r"good afternoon( anton)?", _pick("Afternoon. Still alive? Good.", "Good afternoon. What's the plan?")),
    (r"good evening( anton)?", _pick("Evening. Long day?", "Good evening. I kept the lights on.")),
    (r"(good ?night|night)( anton)?", _pick("Night. I'll keep watch.", "Sleep well. I'll tidy up my brain while you're out.")),
    (r"(hi|hello|hey|yo|sup|heya)( anton)?", _pick("Hey. What's up?", "Yo. I'm here.", "Hey boss.")),
    (r"(thanks|thank you|thx|cheers)( anton)?", _pick("Anytime.", "Don't mention it.", "Easy.")),
    (r"how are you( doing)?|how('s| is) it going", _pick("Running smooth, no fires. You?", "Sharp as ever. What's going on?")),
    (r"(are you|you) (there|awake|alive)", _pick("Always.", "Right here.")),
    (r"what('s| is) the time|what time is it|time", _time),
    (r"what('s| is) (the )?(date|day)( today)?|what day is it", _date),
    (r"test(ing)?( 1 2 3)?", _pick("Loud and clear.", "Receiving you.")),
]


class FastPath:
    def __init__(self, store, cfg):
        self.store = store
        self.promote = cfg["fastpath"]["promote_after"]
        self.fuzzy = cfg["fastpath"]["fuzzy"]

    def seen(self, text):
        n = norm(text)
        if n and len(n.split()) <= 10:
            self.store.phrase_seen(n, text)

    def _usable(self, row):
        return row and row[1] and (row[2] or row[0] >= self.promote)

    def match(self, text):
        n = norm(text)
        if not n:
            return None
        for pat, fn in SEEDS:
            if re.fullmatch(pat, n):
                return fn()
        row = self.store.phrase_get(n)
        if self._usable(row):
            return row[1]
        close = difflib.get_close_matches(n, self.store.phrase_keys(), n=1, cutoff=self.fuzzy)
        if close:
            row = self.store.phrase_get(close[0])
            if self._usable(row):
                return row[1]
        return None

    def learn(self, text, reply):
        n = norm(text)
        if n and len(n.split()) <= 8 and len(reply) <= 160:
            self.store.phrase_set(n, text, reply, 0)

    def add_hard(self, phrase, reply):
        self.store.phrase_set(norm(phrase), phrase, reply, 1)


def seed_texts():
    return [o for _, fn in SEEDS for o in getattr(fn, "opts", ())]
