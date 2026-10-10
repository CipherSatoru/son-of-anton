import os, threading, webbrowser


def start(url, on_update, on_quit):
    """Optional system-tray icon (pystray). Silently skipped if unavailable."""
    try:
        import pystray
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (64, 64), "#05080d")
        d = ImageDraw.Draw(im)
        d.ellipse((8, 8, 56, 56), outline="#38e1ff", width=5)
        d.ellipse((24, 24, 40, 40), fill="#38e1ff")
        menu = pystray.Menu(pystray.MenuItem("Open dashboard", lambda: webbrowser.open(url), default=True),
                            pystray.MenuItem("Check for updates", lambda: on_update()),
                            pystray.MenuItem("Quit", lambda icon, item: (icon.stop(), on_quit())))
        icon = pystray.Icon("anton", im, "Son of Anton", menu)
        threading.Thread(target=icon.run, daemon=True).start()
        return True
    except Exception:
        return False
