"""Extra tools. The design follows the open-source Hermes Agent (MIT, Nous Research) core toolset:
patch, execute_code, background processes, todo, session_search, cronjob, delegate_task, clarify - plus desktop/web helpers."""
import ast, json, math, operator, os, re, shutil, subprocess, sys, time, urllib.parse, webbrowser
from pathlib import Path
from . import config, inputctl, net
from .tools import tool, CTX, HOME, SYS, _safe, DANGER

LOCK = {"delegating": False}


def _jload(name, default):
    try:
        return json.loads((config.DATA / f"{name}.json").read_text(encoding="utf-8"))
    except Exception:
        return default


def _jsave(name, obj):
    (config.DATA / f"{name}.json").write_text(json.dumps(obj, indent=1), encoding="utf-8")


def _guard_write(p):
    if HOME not in p.parents and p != HOME:
        raise PermissionError("can only modify files inside the home folder")


# ---------- files / code (Hermes: patch, search_files, execute_code) ----------
@tool("patch_file", "Edit a file by replacing exact text (tolerates whitespace/indent differences). Better than rewriting the whole file",
      "path, old, new, replace_all=false")
def patch_file(path, old, new, replace_all=False):
    p = _safe(path)
    _guard_write(p)
    txt = p.read_text(encoding="utf-8").replace("\r\n", "\n")
    old, new = str(old).replace("\r\n", "\n"), str(new).replace("\r\n", "\n")
    if old in txt:
        c = txt.count(old)
        if c > 1 and not replace_all:
            return f"refused: {c} matches. Add more surrounding text or set replace_all=true"
        out = txt.replace(old, new) if replace_all else txt.replace(old, new, 1)
    else:
        lines, ol = txt.split("\n"), [l.strip() for l in old.strip("\n").split("\n")]
        hit = next((i for i in range(len(lines) - len(ol) + 1) if [l.strip() for l in lines[i:i + len(ol)]] == ol), None)
        if hit is None:
            return "error: old text not found (read_file first and copy it exactly)"
        lines[hit:hit + len(ol)] = new.strip("\n").split("\n")
        out = "\n".join(lines)
    p.write_text(out, encoding="utf-8")
    return f"patched {p}"


@tool("search_in_files", "Grep: find a regex/text inside files under a folder", "pattern, root='~', glob='*'")
def search_in_files(pattern, root="~", glob="*"):
    rx, out, end = re.compile(pattern, re.I), [], time.time() + 15
    for d, dirs, fs in os.walk(_safe(root)):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("node_modules", "__pycache__", ".venv", "venv")]
        for f in Path(d).glob(glob):
            if not f.is_file() or f.stat().st_size > 1_500_000:
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        out.append(f"{f}:{i}: {line.strip()[:140]}")
                        if len(out) >= 25:
                            return "\n".join(out)
            except Exception:
                pass
        if time.time() > end:
            break
    return "\n".join(out) or "no matches"


@tool("execute_code", "Run a Python snippet (stdlib + installed packages) and return its output. Use for calculations, data processing, scripts", "code")
def execute_code(code):
    d = config.DATA / "tmp"
    d.mkdir(exist_ok=True)
    f = d / f"run_{int(time.time() * 1000)}.py"
    f.write_text(code, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(f)], capture_output=True, text=True, timeout=40, cwd=str(HOME))
        return ((r.stdout or "") + (r.stderr or ""))[-2000:] or f"exit {r.returncode}"
    except subprocess.TimeoutExpired:
        return "error: timed out after 40s"
    finally:
        f.unlink(missing_ok=True)


@tool("powershell", "Run a PowerShell command (Windows only, 30s)", "cmd")
def powershell(cmd):
    if SYS != "Windows":
        return "error: only on Windows (use run_shell)"
    if DANGER.search(cmd) and not CTX["cfg"].get("allow_dangerous"):
        return "refused: destructive command blocked"
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=30,
                       creationflags=0x08000000)
    return ((r.stdout or "") + (r.stderr or ""))[-1800:] or f"exit {r.returncode}"


# ---------- background processes (Hermes: process_manage) ----------
PROCS = {}


@tool("start_process", "Start a long-running command in the background (server, download, build). Returns an id", "cmd")
def start_process(cmd):
    if DANGER.search(cmd) and not CTX["cfg"].get("allow_dangerous"):
        return "refused: destructive command blocked"
    d = config.DATA / "proc"
    d.mkdir(exist_ok=True)
    pid = f"p{len(PROCS) + 1}"
    log = open(d / f"{pid}.log", "wb")
    kw = {"creationflags": 0x08000000} if SYS == "Windows" else {"start_new_session": True}
    PROCS[pid] = (subprocess.Popen(cmd, shell=True, stdout=log, stderr=subprocess.STDOUT, cwd=str(HOME), **kw), d / f"{pid}.log", cmd)
    return f"started {pid}"


@tool("process_list", "List background processes started with start_process", "")
def process_list():
    return "\n".join(f"{k}: {'running' if v[0].poll() is None else 'exit ' + str(v[0].returncode)}  {v[2][:60]}" for k, v in PROCS.items()) or "none"


@tool("process_output", "Read the latest output of a background process", "id")
def process_output(id):
    return PROCS[id][1].read_text(errors="replace")[-1800:] or "(no output yet)"


@tool("process_kill", "Stop a background process", "id")
def process_kill(id):
    PROCS[id][0].terminate()
    return f"stopped {id}"


# ---------- planning / memory / agents (Hermes: todo, session_search, clarify, delegate_task) ----------
@tool("todo", "Keep a task list. action = add | list | done | clear. For add give text; for done give the number", "action, text='', n=0")
def todo(action, text="", n=0):
    items = _jload("todo", [])
    if action == "add" and text:
        items.append({"t": text, "done": False})
    elif action == "done" and 0 < int(n) <= len(items):
        items[int(n) - 1]["done"] = True
    elif action == "clear":
        items = [i for i in items if not i["done"]]
    _jsave("todo", items)
    return "\n".join(f"{i}. [{'x' if t['done'] else ' '}] {t['t']}" for i, t in enumerate(items, 1)) or "empty"


@tool("session_search", "Search past conversations with the user", "query")
def session_search(query):
    rows = CTX["store"].q("SELECT role,text FROM convo WHERE text LIKE ? ORDER BY id DESC LIMIT 10", (f"%{query}%",))
    return "\n".join(f"{r}: {t[:160]}" for r, t in rows) or "nothing found"


@tool("clarify", "Ask the user a question when you are truly blocked, then stop and wait for their answer", "question")
def clarify(question):
    return "ASK_USER: finish now with a final answer that asks: " + str(question)


@tool("delegate_task", "Hand a sub-task to a fresh helper agent and get its result (use for independent research/work)", "task")
def delegate_task(task):
    if LOCK["delegating"] or not CTX.get("delegate"):
        return "refused: cannot delegate from here"
    LOCK["delegating"] = True
    try:
        return CTX["delegate"](task)
    finally:
        LOCK["delegating"] = False


# ---------- scheduler (Hermes: cronjob) ----------
def _next_at(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    t = time.localtime()
    cand = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, m, 0, 0, 0, -1))
    return cand if cand > time.time() else cand + 86400


@tool("cron_add", "Schedule a task for yourself: every_minutes=N (repeat), or at='HH:MM' (daily), or in_minutes=N (once)",
      "task, every_minutes=0, at='', in_minutes=0")
def cron_add(task, every_minutes=0, at="", in_minutes=0):
    jobs = _jload("cron", [])
    j = {"id": int(time.time()), "task": task, "every": float(every_minutes), "at": at, "once": bool(float(in_minutes))}
    j["next"] = time.time() + float(in_minutes) * 60 if j["once"] else (_next_at(at) if at else time.time() + max(1.0, j["every"]) * 60)
    jobs.append(j)
    _jsave("cron", jobs)
    return f"scheduled #{j['id']}: {task}"


@tool("cron_list", "List scheduled tasks", "")
def cron_list():
    return "\n".join(f"#{j['id']} {j['task']} (every {j['every']}m)" if j["every"] else f"#{j['id']} {j['task']} (at {j['at'] or 'once'})"
                     for j in _jload("cron", [])) or "none"


@tool("cron_remove", "Delete a scheduled task by id", "id")
def cron_remove(id):
    _jsave("cron", [j for j in _jload("cron", []) if str(j["id"]) != str(id)])
    return "removed"


async def cron_loop(brain):
    import asyncio
    while True:
        await asyncio.sleep(20)
        try:
            jobs, now, keep = _jload("cron", []), time.time(), []
            for j in jobs:
                if j["next"] <= now:
                    asyncio.get_running_loop().create_task(brain.handle(j["task"], "cron"))
                    if j.get("once"):
                        continue
                    j["next"] = now + j["every"] * 60 if j.get("every") else _next_at(j["at"])
                keep.append(j)
            if len(keep) != len(jobs) or any(a != b for a, b in zip(keep, jobs)):
                _jsave("cron", keep)
        except Exception:
            pass


# ---------- desktop ----------
@tool("drag", "Drag the mouse from (x1,y1) to (x2,y2)", "x1, y1, x2, y2")
def drag(x1, y1, x2, y2):
    inputctl.drag(int(float(x1)), int(float(y1)), int(float(x2)), int(float(y2)))
    return "dragged"


@tool("windows_list", "List open windows (titles)", "")
def windows_list():
    if SYS == "Windows":
        import ctypes
        u = ctypes.windll.user32
        out = []
        cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def f(h, _):
            if u.IsWindowVisible(h):
                n = u.GetWindowTextLengthW(h)
                if n:
                    b = ctypes.create_unicode_buffer(n + 1)
                    u.GetWindowTextW(h, b, n + 1)
                    out.append(b.value)
            return True
        u.EnumWindows(cb(f), 0)
        return "\n".join(out[:40])
    if shutil.which("wmctrl"):
        return subprocess.run(["wmctrl", "-l"], capture_output=True, text=True).stdout[-1500:]
    return "error: needs wmctrl (Linux)"


@tool("focus_window", "Bring a window to the front by (part of) its title", "title")
def focus_window(title):
    if SYS == "Windows":
        import ctypes
        u = ctypes.windll.user32
        found = []
        cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def f(h, _):
            n = u.GetWindowTextLengthW(h)
            if n and u.IsWindowVisible(h):
                b = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                if title.lower() in b.value.lower():
                    found.append(h)
            return True
        u.EnumWindows(cb(f), 0)
        if not found:
            return "no window with that title"
        u.ShowWindow(found[0], 9)
        inputctl.press("alt")  # lets SetForegroundWindow succeed
        u.SetForegroundWindow(found[0])
        return "focused"
    if shutil.which("wmctrl"):
        return "focused" if subprocess.run(["wmctrl", "-a", title]).returncode == 0 else "no window with that title"
    return "error: needs wmctrl (Linux)"


@tool("open_folder", "Open a folder in the file manager", "path='~'")
def open_folder(path="~"):
    p = str(_safe(path))
    os.startfile(p) if SYS == "Windows" else subprocess.Popen(["open" if SYS == "Darwin" else "xdg-open", p])
    return f"opened {p}"


# ---------- web / media ----------
@tool("news", "Latest news headlines (optionally about a topic)", "topic=''")
def news(topic=""):
    return net.news(topic)


@tool("net_status", "Check if the internet works and how fast it responds", "")
def net_status():
    t = time.time()
    ok = net.online(0)
    return f"online, {int((time.time() - t) * 1000)} ms" if ok else "OFFLINE: no internet connection"


@tool("download_file", "Download a file from a URL into Downloads", "url, name=''")
def download_file(url, name=""):
    name = name or urllib.parse.unquote(url.split("?")[0].rstrip("/").split("/")[-1]) or "download"
    d = HOME / "Downloads"
    d.mkdir(exist_ok=True)
    (d / name).write_bytes(net.get(url, raw=True, timeout=120))
    return f"saved {d / name}"


@tool("image_generate", "Generate an image from a text prompt (free) and open it", "prompt")
def image_generate(prompt):
    d = config.DATA / "images"
    d.mkdir(exist_ok=True)
    p = d / f"img_{int(time.time())}.jpg"
    p.write_bytes(net.get("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt), params={"width": 1024, "height": 1024, "nologo": "true"}, raw=True, timeout=90))
    os.startfile(str(p)) if SYS == "Windows" else subprocess.Popen(["open" if SYS == "Darwin" else "xdg-open", str(p)])
    return f"saved and opened {p}"


@tool("play_music", "Find a song/video on YouTube and play it in the browser", "query")
def play_music(query):
    t = net.get("https://www.youtube.com/results", params={"search_query": query})
    m = re.search(r'"videoId":"([\w-]{11})"', t)
    url = f"https://www.youtube.com/watch?v={m.group(1)}" if m else "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    webbrowser.open(url)
    return f"playing {url}"


# ---------- maths ----------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
        ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FN = {k: getattr(math, k) for k in ("sqrt", "sin", "cos", "tan", "log", "log10", "exp", "floor", "ceil", "factorial", "radians", "degrees")}
_FN.update(abs=abs, round=round, min=min, max=max)
_CONST = {"pi": math.pi, "e": math.e}


def _ev(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp):
        if isinstance(n.op, ast.Pow) and abs(_ev(n.right)) > 200:
            raise ValueError("exponent too large")
        return _OPS[type(n.op)](_ev(n.left), _ev(n.right))
    if isinstance(n, ast.UnaryOp):
        return _OPS[type(n.op)](_ev(n.operand))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FN:
        return _FN[n.func.id](*[_ev(a) for a in n.args])
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    raise ValueError("unsupported expression")


@tool("calc", "Exact calculator. Supports + - * / ** % sqrt sin cos log pi etc.", "expression")
def calc(expression):
    e = str(expression).replace("^", "**")
    if re.fullmatch(r"[\d\s.x+\-*/()%]+", e):
        e = e.replace("x", "*")
    return str(_ev(ast.parse(e, mode="eval").body))
