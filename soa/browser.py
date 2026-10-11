"""Browser automation through Camofox (https://github.com/jo-inc/camofox-browser, MIT): a local anti-detection Firefox
(Camoufox) behind a small REST API. Same API surface Hermes Agent uses. First use sets everything up in the background."""
import atexit, base64, io, os, re, shutil, subprocess, sys, tempfile, threading, time, zipfile
import httpx
from . import config, net
from .tools import tool, CTX

DIR = config.DATA / "camofox"
URL = (os.environ.get("CAMOFOX_URL") or "http://127.0.0.1:9377").rstrip("/")
USER, SESSION = "soa", "default"
NT = os.name == "nt"
_st = {"phase": "idle", "msg": "not set up yet (starts on first use)"}
_proc = {"p": None}
_tab = {"id": None}
_lock = threading.Lock()


def status():
    return {"phase": _st["phase"], "msg": _st["msg"], "up": alive()}


def alive():
    try:
        return httpx.get(URL + "/health", timeout=2).status_code < 500
    except Exception:
        return False


def _node():
    n = shutil.which("node")
    if not n:
        return None
    try:
        v = subprocess.run([n, "--version"], capture_output=True, text=True, timeout=10).stdout.strip().lstrip("v")
        return n if int(v.split(".")[0]) >= 22 else None
    except Exception:
        return None


def _npm():
    return shutil.which("npm.cmd" if NT else "npm") or shutil.which("npm")


def _hidden():
    return {"creationflags": 0x08000000} if NT else {"start_new_session": True}


def _start():
    env = {**os.environ, "CAMOFOX_PORT": URL.rsplit(":", 1)[-1].split("/")[0], "CAMOFOX_CRASH_REPORT_ENABLED": "false"}
    log = open(config.DATA / "camofox.log", "ab")
    _proc["p"] = subprocess.Popen([_node(), "server.js"], cwd=str(DIR), env=env, stdout=log, stderr=log, **_hidden())
    for _ in range(90):
        if alive():
            _st.update(phase="ready", msg="ready")
            return True
        time.sleep(1)
    _st.update(phase="error", msg="server did not start (see data/camofox.log)")
    return False


def _setup():
    try:
        if not _node():
            _st.update(phase="installing", msg="installing Node.js 22+ (one time)...")
            if NT and shutil.which("winget"):
                subprocess.run(["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS", "--silent", "--accept-source-agreements",
                                "--accept-package-agreements"], capture_output=True, timeout=1500)
                for d in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):  # PATH isn't refreshed in this process
                    if d and os.path.isdir(os.path.join(d, "nodejs")):
                        os.environ["PATH"] += os.pathsep + os.path.join(d, "nodejs")
            if not _node():
                _st.update(phase="error", msg="Node.js 22+ is required: install it from nodejs.org, then press Set up browser again")
                return
        if not (DIR / "server.js").exists():
            _st.update(phase="installing", msg="downloading browser server...")
            z = zipfile.ZipFile(io.BytesIO(net.get("https://codeload.github.com/jo-inc/camofox-browser/zip/refs/heads/main", raw=True, timeout=180)))
            tmp = tempfile.mkdtemp()
            z.extractall(tmp)
            shutil.rmtree(DIR, ignore_errors=True)
            shutil.move(os.path.join(tmp, os.listdir(tmp)[0]), str(DIR))
        if not (DIR / "node_modules").exists():
            _st.update(phase="installing", msg="installing browser (first time, ~300 MB, a few minutes)...")
            r = subprocess.run([_npm(), "install", "--no-audit", "--no-fund"], cwd=str(DIR), capture_output=True, text=True, timeout=1800, shell=NT,
                               env={**os.environ, "CAMOFOX_CRASH_REPORT_ENABLED": "false"})
            if r.returncode:
                _st.update(phase="error", msg="npm install failed: " + (r.stderr or "")[-160:])
                return
        _st.update(phase="starting", msg="starting browser...")
        _start()
    except Exception as e:
        _st.update(phase="error", msg=f"{type(e).__name__}: {e}"[:200])


def setup_async():
    if _st["phase"] in ("installing", "starting"):
        return status()
    _st.update(phase="installing", msg="starting setup...")
    threading.Thread(target=_setup, daemon=True).start()
    return status()


def _ensure():
    """Returns None when the browser is ready, else a message for the agent."""
    if alive():
        return None
    if _st["phase"] in ("installing", "starting"):
        return f"browser is still setting up: {_st['msg']}. Tell the user it will be ready in a few minutes."
    if (DIR / "node_modules").exists() and _node():
        with _lock:
            _st.update(phase="starting", msg="starting browser...")
            if _start():
                return None
        return "browser failed to start: " + _st["msg"]
    setup_async()
    return "browser is being installed for the first time (about 300 MB, a few minutes). Tell the user, then continue without it for now."


def shutdown():
    p = _proc.get("p")
    if p and p.poll() is None:
        try:
            if NT:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
            else:
                p.terminate()
        except Exception:
            pass


atexit.register(shutdown)


def _req(method, path, **kw):
    kw.setdefault("timeout", 45)
    r = httpx.request(method, URL + path, **kw)
    r.raise_for_status()
    return r


def _tabid(url="about:blank"):
    if not _tab["id"]:
        _tab["id"] = _req("POST", "/tabs", json={"userId": USER, "listItemId": SESSION, "url": url}).json().get("tabId")
    return _tab["id"]


def _snap(limit=3500):
    d = _req("GET", f"/tabs/{_tabid()}/snapshot", params={"userId": USER}).json()
    s, out, n = d.get("snapshot", ""), [], 0
    for line in s.split("\n"):
        n += len(line) + 1
        if n > limit:
            out.append("... (page continues: scroll or use browser_snapshot after scrolling)")
            break
        out.append(line)
    return "\n".join(out)


def _wrap(fn):
    msg = _ensure()
    if msg:
        return msg
    try:
        return fn()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            _tab["id"] = None
            return "error: the tab was closed. Call browser_open again."
        return f"error: browser HTTP {e.response.status_code}"


@tool("browser_open", "Open a URL in the stealth browser and get a page snapshot with element refs (e1, e2...)", "url")
def browser_open(url):
    def go():
        u = url if url.startswith(("http", "about:")) else "https://" + url
        if _tab["id"]:
            try:
                d = _req("POST", f"/tabs/{_tab['id']}/navigate", json={"userId": USER, "url": u}, timeout=60).json()
            except httpx.HTTPStatusError:
                _tab["id"] = None
                _tabid(u)
                d = {}
        else:
            _tabid(u)
            d = {}
        return f"{d.get('title', '')} {d.get('url', u)}\n" + _snap()
    return _wrap(go)


@tool("browser_snapshot", "Re-read the current page (accessibility tree with element refs)", "")
def browser_snapshot():
    return _wrap(_snap)


@tool("browser_click", "Click an element by ref from the snapshot (e.g. e5)", "ref")
def browser_click(ref):
    def go():
        _req("POST", f"/tabs/{_tabid()}/click", json={"userId": USER, "ref": str(ref).lstrip("@")})
        time.sleep(0.8)
        return "clicked\n" + _snap(2500)
    return _wrap(go)


@tool("browser_type", "Type text into an element by ref; submit=true presses Enter afterwards", "ref, text, submit=false")
def browser_type(ref, text, submit=False):
    def go():
        _req("POST", f"/tabs/{_tabid()}/type", json={"userId": USER, "ref": str(ref).lstrip("@"), "text": str(text)})
        if str(submit).lower() in ("true", "1", "yes"):
            _req("POST", f"/tabs/{_tabid()}/press", json={"userId": USER, "key": "Enter"})
            time.sleep(1.2)
            return "typed and submitted\n" + _snap(2500)
        return "typed"
    return _wrap(go)


@tool("browser_press", "Press a key in the browser (Enter, Tab, Escape, ArrowDown...)", "key")
def browser_press(key):
    return _wrap(lambda: (_req("POST", f"/tabs/{_tabid()}/press", json={"userId": USER, "key": key}), "pressed " + key)[1])


@tool("browser_scroll", "Scroll the page: direction = up | down", "direction")
def browser_scroll(direction="down"):
    return _wrap(lambda: (_req("POST", f"/tabs/{_tabid()}/scroll", json={"userId": USER, "direction": direction}), "scrolled\n" + _snap(2500))[1])


@tool("browser_back", "Go back one page", "")
def browser_back():
    return _wrap(lambda: (_req("POST", f"/tabs/{_tabid()}/back", json={"userId": USER}), _snap(2500))[1])


@tool("browser_vision", "Screenshot the browser page and ask a vision model about it", "question")
def browser_vision(question="Describe this page"):
    def go():
        from PIL import Image
        png = _req("GET", f"/tabs/{_tabid()}/screenshot", params={"userId": USER}).content
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        return CTX["vision"](question, base64.b64encode(buf.getvalue()).decode())
    return _wrap(go)


@tool("browser_close", "Close the browser session", "")
def browser_close():
    try:
        if alive():
            _req("DELETE", f"/sessions/{USER}", timeout=10)
    except Exception:
        pass
    _tab["id"] = None
    return "closed"
