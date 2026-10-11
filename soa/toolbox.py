"""Sends the model only the tools a task is likely to need (names-only list for the rest). Fewer tokens uploaded per step = faster replies."""
import re
from . import tools

CORE = ["open_app", "open_url", "web_search", "fetch_url", "press_keys", "type_text", "click", "look_at_screen", "run_shell",
        "read_file", "write_file", "remember", "recall", "calc", "execute_code", "notify"]
GROUPS = [
    (r"browse|website|web ?page|\bsite\b|log ?in|sign ?in|fill|form|amazon|youtube|github|twitter|reddit|facebook|instagram|\.com|\.org|http|checkout|book|buy",
     ["browser_open", "browser_snapshot", "browser_click", "browser_type", "browser_press", "browser_scroll", "browser_back", "browser_vision", "browser_close"]),
    (r"file|folder|director|code|script|edit|patch|project|repo|git\b|python|grep|install|build|run |server|powershell|process",
     ["patch_file", "search_in_files", "list_dir", "search_files", "start_process", "process_list", "process_output", "process_kill", "powershell", "open_folder"]),
    (r"play|music|song|volume|mute|video|image|picture|draw|generate|download", ["play_music", "volume", "media", "image_generate", "download_file"]),
    (r"remind|schedule|every|daily|later|timer|alarm|todo|to-do|task list|tomorrow", ["set_timer", "schedule_task", "cron_add", "cron_list", "cron_remove", "todo"]),
    (r"window|mouse|drag|scroll|screen|lock|focus|minimi|maximi|kill|cpu|ram|battery|clipboard|copy|paste",
     ["windows_list", "focus_window", "move_mouse", "drag", "scroll", "screen_size", "lock_screen", "system_info", "list_processes", "kill_process", "clipboard_get", "clipboard_set", "screenshot"]),
    (r"news|weather|latest|price|who |what |when |research|find out|look up|headline|internet", ["news", "weather", "net_status", "delegate_task", "session_search"]),
]
_RX = [(re.compile(p, re.I), n) for p, n in GROUPS]


def _fmt(n):
    t = tools.TOOLS[n]
    d = t["desc"]
    return f"{n}({t['args']}): {d if len(d) <= 78 else d[:75] + '...'}"


def select(task):
    sel = [n for n in CORE if n in tools.TOOLS]
    for rx, names in _RX:
        if rx.search(task):
            sel += [n for n in names if n in tools.TOOLS]
    sel += [n for n, t in tools.TOOLS.items() if t.get("skill")]
    seen, out = set(), []
    for n in sel:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def prompt_for(task):
    sel = select(task)
    rest = sorted(n for n in tools.TOOLS if n not in set(sel))
    return "\n".join(_fmt(n) for n in sel), ", ".join(rest)
