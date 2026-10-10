"""Resilient networking: retries, urllib fallback, connectivity check, and a multi-backend web search."""
import html, re, socket, time, urllib.parse, urllib.request
import httpx

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
_on = {"t": 0.0, "v": True}


def online(max_age=15):
    """True if the internet is reachable (cached a few seconds)."""
    if time.time() - _on["t"] < max_age:
        return _on["v"]
    ok = False
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53), ("api.github.com", 443)):
        try:
            socket.create_connection((host, port), 3).close()
            ok = True
            break
        except OSError:
            continue
    _on.update(t=time.time(), v=ok)
    return ok


def get(url, *, params=None, data=None, headers=None, timeout=20, raw=False):
    """GET/POST with 2 httpx tries then urllib. Returns text (or bytes if raw). Raises the last error."""
    h = {**UA, **(headers or {})}
    err = None
    for i in range(2):
        try:
            r = httpx.request("POST" if data is not None else "GET", url, params=params, data=data, headers=h,
                              timeout=timeout, follow_redirects=True)
            if r.status_code < 400:
                return r.content if raw else r.text
            err = RuntimeError(f"HTTP {r.status_code}")
            if r.status_code in (400, 401, 403, 404):
                break
        except Exception as e:
            err = e
        time.sleep(0.4)
    try:  # urllib uses the OS certificate/proxy settings, which sometimes works when httpx doesn't
        u = url + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(u, headers=h, data=urllib.parse.urlencode(data).encode() if data is not None else None)
        body = urllib.request.urlopen(req, timeout=timeout).read()
        return body if raw else body.decode("utf-8", "replace")
    except Exception as e:
        raise err or e


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<.*?>", "", s or ""))).strip()


def _unwrap(href):
    m = re.search(r"uddg=([^&]+)", href)
    return urllib.parse.unquote(m.group(1)) if m else href


def _ddgs(q):
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        return [f'{r.get("title")} - {r.get("href")}\n  {r.get("body", "")}' for r in DDGS().text(q, max_results=6)]
    except Exception:
        return []


def _ddg_lite(q):
    t = get("https://lite.duckduckgo.com/lite/", data={"q": q})
    out = []
    for m in re.finditer(r"<a[^>]+class=['\"]result-link['\"][^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>.*?class=['\"]result-snippet['\"][^>]*>(.*?)</td>", t, re.S):
        out.append(f"{_clean(m.group(2))} - {_unwrap(m.group(1))}\n  {_clean(m.group(3))}")
    return out[:6]


def _bing(q):
    t = get("https://www.bing.com/search", params={"q": q, "setlang": "en"})
    out = []
    for blk in re.findall(r'<li class="b_algo".*?</li>', t, re.S):
        a = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)
        p = re.search(r"<p[^>]*>(.*?)</p>", blk, re.S)
        if a:
            out.append(f"{_clean(a.group(2))} - {a.group(1)}\n  {_clean(p.group(1)) if p else ''}")
    return out[:6]


def _wiki(q):
    import json
    j = json.loads(get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": 5}))
    return [f'{x["title"]} - https://en.wikipedia.org/wiki/{urllib.parse.quote(x["title"].replace(" ", "_"))}\n  {_clean(x["snippet"])}'
            for x in j.get("query", {}).get("search", [])]


def search(q):
    errs = []
    for fn in (_ddgs, _ddg_lite, _bing, _wiki):
        try:
            r = fn(q)
            if r:
                return "\n".join(r)
        except Exception as e:
            errs.append(f"{fn.__name__}:{type(e).__name__}")
    if not online():
        return "error: no internet connection right now"
    return "no results (" + ", ".join(errs) + ")"


def news(topic=""):
    import xml.etree.ElementTree as ET
    url = "https://news.google.com/rss/search" if topic else "https://news.google.com/rss"
    t = get(url, params={"q": topic, "hl": "en-US", "gl": "US", "ceid": "US:en"} if topic else {"hl": "en-US", "gl": "US", "ceid": "US:en"})
    items = ET.fromstring(t).findall(".//item")[:8]
    return "\n".join(f'{i.findtext("title")} ({i.findtext("pubDate", "")[:16]})' for i in items) or "no news found"


def page_text(url, limit=3500):
    t = get(url)
    t = re.sub(r"(?s)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", t)
    return _clean(t)[:limit]
