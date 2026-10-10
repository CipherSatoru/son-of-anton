import sqlite3, threading, time, re


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS phrases(norm TEXT PRIMARY KEY, raw TEXT, count INT DEFAULT 0,
            reply TEXT, hard INT DEFAULT 0, last REAL);
        CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT);
        CREATE TABLE IF NOT EXISTS convo(id INTEGER PRIMARY KEY, ts REAL, role TEXT, text TEXT, src TEXT);
        """)

    def q(self, sql, args=(), commit=False):
        with self.lock:
            cur = self.db.execute(sql, args)
            rows = cur.fetchall()
            if commit:
                self.db.commit()
            return rows

    def log(self, role, text, src="?"):
        self.q("INSERT INTO convo(ts,role,text,src) VALUES(?,?,?,?)", (time.time(), role, text, src), True)

    def recent(self, n=8):
        rows = self.q("SELECT role,text,src FROM convo ORDER BY id DESC LIMIT ?", (n,))
        return [{"role": r, "text": t, "src": s} for r, t, s in reversed(rows)]

    def phrase_seen(self, norm, raw):
        self.q("INSERT INTO phrases(norm,raw,count,last) VALUES(?,?,1,?) "
               "ON CONFLICT(norm) DO UPDATE SET count=count+1,last=excluded.last", (norm, raw, time.time()), True)

    def phrase_get(self, norm):
        r = self.q("SELECT count,reply,hard FROM phrases WHERE norm=?", (norm,))
        return r[0] if r else None

    def phrase_set(self, norm, raw, reply, hard=0):
        self.q("INSERT INTO phrases(norm,raw,count,reply,hard,last) VALUES(?,?,1,?,?,?) "
               "ON CONFLICT(norm) DO UPDATE SET reply=excluded.reply,hard=excluded.hard",
               (norm, raw, reply, hard, time.time()), True)

    def phrase_keys(self):
        return [r[0] for r in self.q("SELECT norm FROM phrases WHERE reply IS NOT NULL ORDER BY count DESC LIMIT 500")]

    def top_phrases(self, n=10):
        return [{"phrase": r[0], "count": r[1], "cached": bool(r[2]), "hard": bool(r[3])} for r in
                self.q("SELECT norm,count,reply,hard FROM phrases ORDER BY count DESC LIMIT ?", (n,))]

    def add_memory(self, kind, text):
        text = text.strip()
        if not text or self.q("SELECT 1 FROM memory WHERE kind=? AND text=?", (kind, text)):
            return False
        self.q("INSERT INTO memory(ts,kind,text) VALUES(?,?,?)", (time.time(), kind, text), True)
        return True

    def memories(self, kind=None, limit=20):
        if kind:
            rows = self.q("SELECT ts,kind,text FROM memory WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit))
        else:
            rows = self.q("SELECT ts,kind,text FROM memory WHERE kind!='cycle' ORDER BY id DESC LIMIT ?", (limit,))
        return [{"ts": t, "kind": k, "text": x} for t, k, x in rows]

    def search_memory(self, query, limit=8):
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2][:5]
        if not words:
            return self.memories(limit=limit)
        cond = " OR ".join(["lower(text) LIKE ?"] * len(words))
        rows = self.q(f"SELECT ts,kind,text FROM memory WHERE kind!='cycle' AND ({cond}) ORDER BY id DESC LIMIT ?",
                      tuple(f"%{w}%" for w in words) + (limit,))
        return [{"ts": t, "kind": k, "text": x} for t, k, x in rows]

    def cycles_today(self):
        start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        return self.q("SELECT COUNT(*) FROM memory WHERE kind='cycle' AND ts>=?", (start,))[0][0]
