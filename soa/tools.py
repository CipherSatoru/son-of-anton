"""PC-control + utility tools, plus skill loader (builtin skills/ and self-written data/skills/)."""
import ast, importlib.util, os, platform, re, shutil, subprocess, threading, time, webbrowser
from pathlib import Path
import httpx
from . import config

TOOLS = {}
CTX = {"store": None, "notify": lambda m: None, "cfg": {}, "vision": None, "run_task": None}
SYS = platform.system()
HOME = Path.home()
UA = {"User-Agent": "Mozilla/5.0 (SonOfAnton)"}


def tool(name, desc, args=""):
    def d(fn):
        TOOLS[name] = {"fn": fn, "desc": desc, "args": args}
        return fn
    return d


def _pg():
    import pyautogui
    pyautogui.PAUSE = 0.05
    return pyautogui


def describe():
    return "\n".join(f'- {n}({t["args"]}): {t["desc"]}' for n, t in sorted(TOOLS.items()))


def call(name, args):
    t = TOOLS.get(name)
    if not t:
        return f"error: unknown tool '{name}'. Available: {', '.join(sorted(TOOLS))}"
    try:
        out = t["fn"](**(args or {}))
        return str(out if out is not None else "done")[:2500]
    except TypeError as e:
        return f"error: bad arguments for {name}({t['args']}): {e}"
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"


# ---------- apps / web ----------
@tool("open_app", "Open an application or file by name or path", "name")
def open_app(name):
    if SYS == "Windows":
        try:
            os.startfile(name)
        except OSError:
            subprocess.Popen(f'start "" "{name}"', shell=True)
    elif SYS == "Darwin":
        subprocess.Popen(["open", "-a", name])
    else:
        exe = shutil.which(name) or shutil.which(name.lower()) or name
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return f"opened {name}"


@tool("open_url", "Open a URL in the default browser", "url")
def open_url(url):
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"opened {url}"


@tool("web_search", "Search the web (DuckDuckGo). Returns top results with snippets", "query")
def web_search(query):
    r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=UA, timeout=20, follow_redirects=True)
    items = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
    out = []
    for href, title, snip in items[:6]:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote
            href = unquote(m.group(1))
        clean = lambda s: re.sub(r"\s+", " ", re.sub(r"<.*?>", "", s)).strip()
        out.append(f"{clean(title)} - {href}\n  {clean(snip)}")
    return "\n".join(out) or "no results"


@tool("fetch_url", "Download a web page and return its readable text", "url")
def fetch_url(url):
    r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
    t = re.sub(r"(?s)<(script|style|noscript).*?</\1>", " ", r.text)
    t = re.sub(r"<.*?>", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:3500]


@tool("weather", "Current weather for a city", "city")
def weather(city):
    return httpx.get(f"https://wttr.in/{city}?format=3", headers=UA, timeout=15).text.strip()


# ---------- keyboard / mouse / screen ----------
@tool("type_text", "Type text at the current cursor (works with any language)", "text")
def type_text(text):
    pg = _pg()
    if text.isascii():
        pg.write(text, interval=0.008)
    else:
        import pyperclip
        pyperclip.copy(text)
        pg.hotkey("command" if SYS == "Darwin" else "ctrl", "v")
    return "typed"


@tool("press_keys", "Press a key or combo, e.g. 'enter' or 'ctrl+shift+t' or 'alt+f4'", "keys")
def press_keys(keys):
    parts = [k.strip() for k in keys.lower().split("+")]
    _pg().hotkey(*parts) if len(parts) > 1 else _pg().press(parts[0])
    return f"pressed {keys}"


@tool("click", "Click at screen coordinates", "x, y, button='left', clicks=1")
def click(x, y, button="left", clicks=1):
    _pg().click(int(x), int(y), button=button, clicks=int(clicks))
    return f"clicked {x},{y}"


@tool("move_mouse", "Move mouse to coordinates", "x, y")
def move_mouse(x, y):
    _pg().moveTo(int(x), int(y), duration=0.15)
    return "moved"


@tool("scroll", "Scroll up (positive) or down (negative)", "amount")
def scroll(amount):
    _pg().scroll(int(amount))
    return "scrolled"


@tool("screen_size", "Screen resolution and current mouse position", "")
def screen_size():
    pg = _pg()
    return f"size={tuple(pg.size())} mouse={tuple(pg.position())}"


@tool("screenshot", "Take a screenshot; returns the saved file path", "")
def screenshot():
    d = config.DATA / "shots"
    d.mkdir(exist_ok=True)
    p = d / time.strftime("%Y%m%d-%H%M%S.png")
    _pg().screenshot().save(p)
    return str(p)


@tool("volume", "Control volume: action = up | down | mute | set (with level 0-100)", "action, level=50")
def volume(action, level=50):
    level = max(0, min(100, int(level)))
    if SYS == "Windows":
        pg = _pg()
        if action == "mute":
            pg.press("volumemute")
        elif action == "set":
            pg.press("volumedown", presses=50)
            pg.press("volumeup", presses=level // 2)
        else:
            pg.press("volumeup" if action == "up" else "volumedown", presses=5)
    elif SYS == "Darwin":
        cmd = {"mute": "set volume with output muted", "set": f"set volume output volume {level}",
               "up": "set volume output volume ((output volume of (get volume settings)) + 10)",
               "down": "set volume output volume ((output volume of (get volume settings)) - 10)"}[action]
        subprocess.run(["osascript", "-e", cmd])
    else:
        a = {"mute": ["set-sink-mute", "@DEFAULT_SINK@", "toggle"], "set": ["set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
             "up": ["set-sink-volume", "@DEFAULT_SINK@", "+10%"], "down": ["set-sink-volume", "@DEFAULT_SINK@", "-10%"]}[action]
        subprocess.run(["pactl"] + a)
    return f"volume {action}"


@tool("media", "Media key: playpause | next | prev | stop", "action")
def media(action):
    key = {"playpause": "playpause", "next": "nexttrack", "prev": "prevtrack", "stop": "stop"}[action]
    _pg().press(key)
    return action


@tool("lock_screen", "Lock the computer", "")
def lock_screen():
    if SYS == "Windows":
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif SYS == "Darwin":
        subprocess.run(["pmset", "displaysleepnow"])
    else:
        subprocess.run(["loginctl", "lock-session"])
    return "locked"


def _jpeg_b64(path):
    import base64, io
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((1280, 1280))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode()


@tool("look_at_screen", "SEE the screen: screenshot + vision model answers a question about it", "question")
def look_at_screen(question="Describe what is on the screen"):
    return CTX["vision"](question, _jpeg_b64(screenshot()))


@tool("describe_image", "Ask a vision model about an image file", "path, question")
def describe_image(path, question="Describe this image"):
    return CTX["vision"](question, _jpeg_b64(_safe(path)))


# ---------- system ----------
@tool("system_info", "CPU, RAM, disk, battery status", "")
def system_info():
    import psutil
    b = psutil.sensors_battery()
    return (f"cpu={psutil.cpu_percent(interval=0.5)}% ram={psutil.virtual_memory().percent}% "
            f"disk={psutil.disk_usage(str(HOME)).percent}% battery={'n/a' if not b else f'{b.percent:.0f}% plugged={b.power_plugged}'}")


@tool("list_processes", "List running processes (optionally filtered by name)", "filter=''")
def list_processes(filter=""):
    import psutil
    names = sorted({p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"] and filter.lower() in p.info["name"].lower()})
    return ", ".join(names[:60])


@tool("kill_process", "Terminate processes by name", "name")
def kill_process(name):
    import psutil
    n = 0
    for p in psutil.process_iter(["name"]):
        if p.info["name"] and p.info["name"].lower() == name.lower():
            p.terminate()
            n += 1
    return f"terminated {n}"


DANGER = re.compile(r"(rm\s+-\w*r\w*f?\s+(/|~|\*)|mkfs|\bdd\s+if=|format\s+[a-z]:|del\s+/[sfq]|rd\s+/s|rmdir\s+/s|"
                    r"shutdown|reboot|poweroff|reg\s+delete|:\(\)\s*\{|>\s*/dev/sd|chmod\s+-R\s+777\s+/|diskpart)", re.I)


@tool("run_shell", "Run a shell command (30s timeout). Destructive commands are blocked", "cmd")
def run_shell(cmd):
    if DANGER.search(cmd) and not CTX["cfg"].get("allow_dangerous"):
        return "refused: destructive command blocked (set allow_dangerous in config.json to override)"
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=str(HOME))
    return ((r.stdout or "") + (r.stderr or ""))[-1800:] or f"exit {r.returncode}"


@tool("clipboard_get", "Read the clipboard", "")
def clipboard_get():
    import pyperclip
    return pyperclip.paste()


@tool("clipboard_set", "Put text on the clipboard", "text")
def clipboard_set(text):
    import pyperclip
    pyperclip.copy(text)
    return "copied"


# ---------- files ----------
def _safe(p):
    p = Path(p).expanduser()
    p = p if p.is_absolute() else HOME / p
    return p.resolve()


@tool("read_file", "Read a text file", "path")
def read_file(path):
    return _safe(path).read_text(encoding="utf-8", errors="replace")[:3500]


@tool("write_file", "Write a text file inside the home folder", "path, content")
def write_file(path, content):
    p = _safe(path)
    if HOME not in p.parents and p != HOME:
        return "refused: can only write inside the home folder"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {p}"


@tool("list_dir", "List a folder", "path='~'")
def list_dir(path="~"):
    return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in _safe(path).iterdir())[:80])


@tool("search_files", "Find files by name fragment under a folder", "name, root='~'")
def search_files(name, root="~"):
    end, out = time.time() + 10, []
    for d, _, fs in os.walk(_safe(root)):
        out += [os.path.join(d, f) for f in fs if name.lower() in f.lower()]
        if len(out) >= 15 or time.time() > end:
            break
    return "\n".join(out[:15]) or "none found"


# ---------- assistant utilities ----------
@tool("get_time", "Current date and time", "")
def get_time():
    return time.strftime("%A %d %B %Y, %H:%M")


@tool("notify", "Show/speak a message to the user right now", "message")
def notify(message):
    CTX["notify"](message)
    return "sent"


@tool("set_timer", "Remind the user after N seconds", "seconds, message")
def set_timer(seconds, message):
    threading.Timer(float(seconds), lambda: CTX["notify"](f"Reminder: {message}")).start()
    return f"timer set for {seconds}s"


@tool("schedule_task", "Run a task by yourself later (after N seconds) and tell the user the result", "seconds, task")
def schedule_task(seconds, task):
    threading.Timer(float(seconds), lambda: CTX["run_task"](task)).start()
    return f"will do '{task}' in {seconds}s"


@tool("wait", "Pause for a few seconds (max 10)", "seconds")
def wait(seconds):
    time.sleep(min(float(seconds), 10))
    return "waited"


@tool("remember", "Save a durable fact about the user or their preferences", "fact")
def remember(fact):
    return "saved" if CTX["store"].add_memory("fact", fact) else "already known"


@tool("recall", "Search long-term memory", "query")
def recall(query):
    return "\n".join(f'[{m["kind"]}] {m["text"]}' for m in CTX["store"].search_memory(query)) or "nothing found"


# ---------- skills (Hermes-style self-extension) ----------
BAD_IMPORT = {"subprocess", "shutil", "ctypes", "pty", "socket", "multiprocessing", "importlib"}
BAD_CALL = {"eval", "exec", "compile", "__import__", "system", "popen", "remove", "unlink", "rmtree",
            "rmdir", "kill", "startfile", "Popen", "chmod", "rename", "replace"}


def validate_skill(code):
    """Return None if the skill source is acceptable, else a reason."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"syntax error: {e}"
    has_run, names = False, set()
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "run":
            has_run = True
        if isinstance(n, ast.Assign):
            names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    if not has_run or not {"NAME", "DESCRIPTION"} <= names:
        return "skill needs NAME, DESCRIPTION, and def run(**kwargs)"
    for n in ast.walk(tree):
        if isinstance(n, ast.Import) and any(a.name.split(".")[0] in BAD_IMPORT for a in n.names):
            return "forbidden import"
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in BAD_IMPORT:
            return "forbidden import"
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if nm in BAD_CALL:
                return f"forbidden call: {nm}"
            if nm == "open" and len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and any(c in str(n.args[1].value) for c in "wax+"):
                return "forbidden: file writing"
    return None


def _load_skill(path, validate):
    code = path.read_text(encoding="utf-8")
    if validate and validate_skill(code):
        return None
    spec = importlib.util.spec_from_file_location("skill_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    name = "skill_" + re.sub(r"\W+", "_", str(mod.NAME)).strip("_")
    args = getattr(mod, "ARGS", {})
    TOOLS[name] = {"fn": lambda **kw: mod.run(**kw), "desc": str(mod.DESCRIPTION),
                   "args": ", ".join(args) if isinstance(args, dict) else str(args), "skill": True}
    return name


def load_skills():
    loaded = []
    for d, validate in ((config.ROOT / "skills", False), (config.DATA / "skills", True)):
        for f in sorted(d.glob("*.py")):
            try:
                n = _load_skill(f, validate)
                if n:
                    loaded.append(n)
            except Exception as e:
                print(f"skill {f.name} failed to load: {e}")
    return loaded


def save_skill(name, code):
    name = re.sub(r"\W+", "_", name.lower()).strip("_")[:40] or "skill"
    bad = validate_skill(code)
    if bad:
        return None, bad
    p = config.DATA / "skills" / f"{name}.py"
    p.write_text(code, encoding="utf-8")
    try:
        tname = _load_skill(p, True)
    except Exception as e:
        p.unlink(missing_ok=True)
        return None, f"load failed: {e}"
    return tname, None


@tool("create_skill", "Write a NEW reusable tool in Python. code must define NAME, DESCRIPTION, ARGS (dict) and def run(**kwargs)->str", "name, code")
def create_skill(name, code):
    t, err = save_skill(name, code)
    return f"skill created: {t}" if t else f"rejected: {err}"


@tool("list_skills", "List learned skills", "")
def list_skills():
    return ", ".join(n for n, t in TOOLS.items() if t.get("skill")) or "none yet"
