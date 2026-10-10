"""Mouse + keyboard control that actually works.
Windows: native SendInput via ctypes (DPI-aware, no dependencies, works for any language).
Linux: xdotool if present, else pyautogui. macOS: pyautogui."""
import platform, re, shutil, subprocess, time

SYS = platform.system()
NAMES = {"enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 9, "space": 0x20, "backspace": 8, "delete": 0x2E, "del": 0x2E,
         "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22, "left": 0x25, "up": 0x26,
         "right": 0x27, "down": 0x28, "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B, "cmd": 0x5B,
         "super": 0x5B, "meta": 0x5B, "capslock": 0x14, "printscreen": 0x2C, "prtsc": 0x2C, "volumeup": 0xAF, "volumedown": 0xAE,
         "volumemute": 0xAD, "playpause": 0xB3, "nexttrack": 0xB0, "prevtrack": 0xB1, "stop": 0xB2, "menu": 0x5D, "numlock": 0x90}
EXTENDED = {0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x5B, 0x5D, 0x2C}
ALIAS = {"control": "ctrl", "return": "enter", "escape": "esc", "windows": "win", "cmd": "win", "super": "win", "meta": "win", "option": "alt"}


def split_keys(keys):
    return [k.strip().lower() for k in re.split(r"\s*\+\s*", str(keys).strip()) if k.strip()]


if SYS == "Windows":
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def _send(*items):
        arr = (INPUT * len(items))(*items)
        if user32.SendInput(len(items), arr, ctypes.sizeof(INPUT)) != len(items):
            raise OSError("SendInput blocked (a window running as Administrator, the lock screen or UAC prompt can block input)")

    def _kb(vk=0, scan=0, flags=0):
        i = INPUT(type=1)
        i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        return i

    def _ms(flags, data=0):
        i = INPUT(type=0)
        i.u.mi = MOUSEINPUT(0, 0, data, flags, 0, 0)
        return i

    def _vk(name):
        n = ALIAS.get(name, name)
        if n in NAMES:
            return NAMES[n]
        if re.fullmatch(r"f(\d{1,2})", n) and 1 <= int(n[1:]) <= 24:
            return 0x70 + int(n[1:]) - 1
        if len(n) == 1:
            r = user32.VkKeyScanW(ord(n))
            if r != -1:
                return r & 0xFF
        raise ValueError(f"unknown key '{name}'")

    def _key(vk, up=False):
        flags = (2 if up else 0) | (1 if vk in EXTENDED else 0)
        _send(_kb(vk, user32.MapVirtualKeyW(vk, 0), flags))

    def press(keys):
        vks = [_vk(k) for k in split_keys(keys)]
        for v in vks:
            _key(v)
            time.sleep(0.01)
        for v in reversed(vks):
            _key(v, True)
            time.sleep(0.01)

    def type_text(text, interval=0.004):
        for ch in text:
            if ch in "\r":
                continue
            if ch == "\n":
                press("enter")
                continue
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):
                code = data[i] | (data[i + 1] << 8)
                _send(_kb(0, code, 4))
                _send(_kb(0, code, 4 | 2))
            time.sleep(interval)

    def move(x, y):
        user32.SetCursorPos(int(x), int(y))

    _BTN = {"left": (2, 4), "right": (8, 16), "middle": (32, 64)}

    def click(x=None, y=None, button="left", clicks=1):
        if x is not None and y is not None:
            move(x, y)
            time.sleep(0.03)
        d, u = _BTN.get(button, _BTN["left"])
        for _ in range(int(clicks)):
            _send(_ms(d))
            _send(_ms(u))
            time.sleep(0.04)

    def drag(x1, y1, x2, y2, duration=0.4):
        move(x1, y1)
        _send(_ms(2))
        steps = 20
        for s in range(1, steps + 1):
            move(x1 + (x2 - x1) * s / steps, y1 + (y2 - y1) * s / steps)
            time.sleep(duration / steps)
        _send(_ms(4))

    def scroll(n):
        _send(_ms(0x800, int(n) * 120 & 0xFFFFFFFF))

    def position():
        p = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    def size():
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

else:
    def _pg():
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.PAUSE = 0.02
        return pyautogui

    _XDO = SYS == "Linux" and shutil.which("xdotool")

    def _xdo(*a):
        subprocess.run(["xdotool", *map(str, a)], check=True, timeout=10)

    def press(keys):
        parts = [ALIAS.get(k, k) for k in split_keys(keys)]
        if _XDO:
            m = {"ctrl": "ctrl", "win": "super", "esc": "Escape", "enter": "Return", "pageup": "Prior", "pagedown": "Next", "backspace": "BackSpace"}
            return _xdo("key", "+".join(m.get(p, p) for p in parts))
        _pg().hotkey(*parts) if len(parts) > 1 else _pg().press(parts[0])

    def type_text(text, interval=0.004):
        if _XDO:
            return _xdo("type", "--delay", "8", text)
        if text.isascii():
            return _pg().write(text, interval=interval)
        import pyperclip
        pyperclip.copy(text)
        _pg().hotkey("command" if SYS == "Darwin" else "ctrl", "v")

    def move(x, y):
        _xdo("mousemove", int(x), int(y)) if _XDO else _pg().moveTo(int(x), int(y), duration=0.1)

    def click(x=None, y=None, button="left", clicks=1):
        if _XDO:
            if x is not None:
                _xdo("mousemove", int(x), int(y))
            return _xdo("click", "--repeat", int(clicks), {"left": 1, "middle": 2, "right": 3}.get(button, 1))
        _pg().click(x, y, clicks=int(clicks), button=button)

    def drag(x1, y1, x2, y2, duration=0.4):
        _pg().moveTo(x1, y1)
        _pg().dragTo(x2, y2, duration=duration, button="left")

    def scroll(n):
        _pg().scroll(int(n))

    def position():
        return tuple(_pg().position())

    def size():
        return tuple(_pg().size())


def screenshot_to(path):
    """Save a screenshot. PIL first (works on Windows/macOS with no extras), pyautogui as fallback."""
    try:
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(path)
        return
    except Exception:
        pass
    import pyautogui
    pyautogui.screenshot().save(path)
