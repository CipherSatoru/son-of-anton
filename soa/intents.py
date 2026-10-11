"""Instant intents: common commands run a tool directly - no model call, no tokens, ~zero latency.
match(text) -> (tool, args, reply_template) or None. '{r}' in the template is replaced by the tool result."""
import re

NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30}
SITES = {"youtube": "youtube.com", "google": "google.com", "gmail": "mail.google.com", "github": "github.com", "twitter": "x.com",
         "facebook": "facebook.com", "reddit": "reddit.com", "whatsapp": "web.whatsapp.com", "netflix": "netflix.com", "amazon": "amazon.com"}
_P = r"^(?:please |hey |ok |okay |can you |could you |just |now )*"


def _n(s):
    s = s.strip().lower()
    return NUM.get(s) or (int(s) if s.isdigit() else None)


def match(text):
    t = re.sub(r"[.!?]+$", "", text.strip())
    tl = t.lower()
    m = re.match(_P + r"(?:open|launch|start|go to|take me to|bring up) (?:the )?(?P<a>.+)$", tl)
    if m:
        a = m.group("a").strip()
        a = re.sub(r"^(?:app|application|program|website|site)\s+", "", a)
        a = re.sub(r"\s+(?:app|application|program|website|site)$", "", a)
        if a in SITES:
            return "open_url", {"url": SITES[a]}, f"Opening {a}."
        if re.search(r"\.[a-z]{2,}(/|$)|^https?://", a):
            return "open_url", {"url": a}, "Opening it."
        if len(a.split()) <= 3 and not re.search(r"\b(file|folder|document|and|then|with|for|that|which)\b", a):
            return "open_app", {"name": a}, f"Opening {a}."
    m = re.match(_P + r"(?:google|search google for|search on google for) (?P<q>.+)$", tl)
    if m:
        return "open_url", {"url": "https://www.google.com/search?q=" + re.sub(r"\s+", "+", m.group("q"))}, "Searching Google."
    m = re.match(_P + r"set (?:the )?volume (?:to )?(?P<n>\d{1,3})(?: ?%| percent)?$", tl) or re.match(_P + r"volume (?P<n>\d{1,3})$", tl)
    if m:
        return "volume", {"action": "set", "level": int(m.group("n"))}, f"Volume {m.group('n')}."
    if re.match(_P + r"(?:turn (?:it |the volume )?up|volume up|louder|raise the volume)$", tl):
        return "volume", {"action": "up"}, "Louder."
    if re.match(_P + r"(?:turn (?:it |the volume )?down|volume down|quieter|lower the volume)$", tl):
        return "volume", {"action": "down"}, "Quieter."
    if re.match(_P + r"(?:mute|unmute)(?: the)?(?: sound| volume| audio)?$", tl):
        return "volume", {"action": "mute"}, "Done."
    if re.match(_P + r"(?:pause|resume|play|stop)(?: the)?(?: music| song| video| media| playback)?$", tl):
        return "media", {"action": "playpause"}, "Done."
    if re.match(_P + r"(?:next|skip)(?: the)?(?: song| track| one)?$", tl):
        return "media", {"action": "next"}, "Next."
    if re.match(_P + r"(?:previous|go back a)(?: song| track)$", tl):
        return "media", {"action": "prev"}, "Previous."
    m = re.match(_P + r"play (?P<q>.{2,60})$", tl)
    if m and not re.search(r"\b(game|chess|a game)\b", m.group("q")):
        q = re.sub(r"^(?:some|a bit of|something by|me some)\s+", "", m.group("q"))
        return "play_music", {"query": q}, f"Playing {q}."
    if re.match(_P + r"(?:take (?:a )?)?screenshot(?: of (?:my|the) screen)?$", tl):
        return "screenshot", {}, "Screenshot saved."
    if re.match(_P + r"(?:what(?:'s| is| do you see)(?: on)? (?:my|the) screen|what do you see|look at (?:my|the) screen|describe (?:my|the) screen)\??$", tl):
        return "look_at_screen", {"question": "Describe what is on the screen briefly."}, "{r}"
    m = re.match(_P + r"(?:what(?:'s| is) )?(?:the )?weather(?: like)?(?: today)?(?: (?:in|for|at) (?P<c>[a-z .'-]+))?$", tl)
    if m:
        return "weather", {"city": (m.group("c") or "").strip()}, "{r}"
    m = re.match(_P + r"(?:what(?:'s| is) )?(?:the )?(?:latest )?news(?: headlines)?(?: (?:about|on) (?P<q>.+))?$", tl)
    if m:
        return "news", {"topic": m.group("q") or ""}, "NEWS"
    m = re.match(_P + r"(?:set (?:a )?)?timer (?:for )?(?P<n>\w+) (?P<u>second|minute|hour)s?$", tl)
    if m and _n(m.group("n")):
        s = _n(m.group("n")) * {"second": 1, "minute": 60, "hour": 3600}[m.group("u")]
        return "set_timer", {"seconds": s, "message": "your timer is up"}, f"Timer set for {m.group('n')} {m.group('u')}s."
    m = re.match(_P + r"remind me in (?P<n>\w+) (?P<u>second|minute|hour)s? to (?P<w>.+)$", tl)
    if m and _n(m.group("n")):
        s = _n(m.group("n")) * {"second": 1, "minute": 60, "hour": 3600}[m.group("u")]
        return "set_timer", {"seconds": s, "message": m.group("w")}, "I'll remind you."
    if re.match(_P + r"lock (?:the |my )?(?:pc|computer|screen|laptop)$", tl):
        return "lock_screen", {}, "Locking."
    if re.match(_P + r"(?:show (?:the )?desktop|minimi[sz]e (?:all|everything))$", tl):
        return "press_keys", {"keys": "win+d"}, "Done."
    if re.match(_P + r"(?:switch|change) (?:the )?window$", tl):
        return "press_keys", {"keys": "alt+tab"}, "Switched."
    if re.match(_P + r"(?:new tab|open a new tab)$", tl):
        return "press_keys", {"keys": "ctrl+t"}, "New tab."
    if re.match(_P + r"close (?:this |the )?tab$", tl):
        return "press_keys", {"keys": "ctrl+w"}, "Closed."
    if re.match(_P + r"close (?:this |the )?(?:window|app)$", tl):
        return "press_keys", {"keys": "alt+f4"}, "Closed."
    m = re.match(_P + r"scroll (?P<d>up|down)$", tl)
    if m:
        return "scroll", {"amount": 6 if m.group("d") == "up" else -6}, "Scrolling."
    m = re.match(_P + r"press (?P<k>[a-z0-9+ ]{1,25})$", tl)
    if m:
        k = m.group("k").replace(" plus ", "+").strip()
        if "+" not in k and len(k.split()) > 1 and k.split()[0] in ("ctrl", "control", "alt", "shift", "win", "windows"):
            k = "+".join(k.split())
        return "press_keys", {"keys": k}, "Done."
    m = re.match(_P + r"type (?P<x>.+)$", t, re.I)
    if m:
        return "type_text", {"text": m.group("x")}, "Typed."
    if re.match(_P + r"(?:system status|how(?:'s| is) (?:the |my )?(?:pc|computer|laptop)|battery(?: level)?|cpu usage|ram usage)$", tl):
        return "system_info", {}, "{r}"
    m = re.match(_P + r"(?:remember|note|take a note)(?: that| this)? (?P<x>.+)$", t, re.I)
    if m:
        return "remember", {"fact": m.group("x")}, "Noted."
    return None


def speak_result(tool, res):
    """Shorten raw tool output for speaking."""
    if tool == "news":
        heads = [re.sub(r"\s*\([^)]*\)\s*$", "", l) for l in res.splitlines()[:4]]
        return "Top headlines: " + "; ".join(heads) + "."
    return res.strip().replace("\n", " ")[:300]
