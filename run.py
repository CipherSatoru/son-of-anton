"""Son of Anton launcher.
  python run.py            run (foreground, auto-restarts on crash)
  python run.py bg         run hidden in the background (+ tray icon)
  python run.py stop|status|logs|open|update
"""
import os, signal, subprocess, sys, time, webbrowser
from pathlib import Path

root = Path(__file__).resolve().parent
data = root / "data"
data.mkdir(exist_ok=True)
NT = os.name == "nt"
venv = root / ".venv" / ("Scripts" if NT else "bin")
py = str(venv / ("python.exe" if NT else "python")) if (venv / ("python.exe" if NT else "python")).exists() else sys.executable
pyw = str(venv / "pythonw.exe") if NT and (venv / "pythonw.exe").exists() else py
PID = data / "supervisor.pid"
CLEAN = {0, 130, 3221225786, -1073741510, -2}


def alive(pid):
    try:
        if NT:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def running():
    try:
        pid = int(PID.read_text())
        return pid if alive(pid) else None
    except Exception:
        return None


def supervise(args, hidden=False):
    PID.write_text(str(os.getpid()))
    child = None
    fails = 0
    try:
        while True:
            t = time.time()
            kw = {"creationflags": 0x08000000} if NT and hidden else {}
            child = subprocess.Popen([pyw if hidden else py, "-m", "soa"] + args, cwd=str(root), **kw)
            code = child.wait()
            if code in CLEAN:
                break
            if code == 75:  # update applied -> restart now
                continue
            fails = fails + 1 if time.time() - t < 30 else 0
            wait = min(5 * (fails + 1), 60)
            print(f"[supervisor] crashed (code {code}), restarting in {wait}s", flush=True)
            time.sleep(wait)
            args = [a for a in args if a != "--open"] + ["--no-browser"]
    except KeyboardInterrupt:
        if child and child.poll() is None:
            try:
                child.wait(timeout=5)
            except Exception:
                child.terminate()
        print("\n  Stopped.")
    finally:
        PID.unlink(missing_ok=True)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "start"
    rest = [a for a in sys.argv[1:] if a != cmd]
    if cmd == "start":
        if running():
            return print("Already running. Use: python run.py open   (or stop)")
        supervise(rest)
    elif cmd == "_bg":
        supervise(["--no-browser", "--tray"], hidden=True)
    elif cmd == "bg":
        if running():
            return print("Already running in the background.")
        log = open(data / "soa.log", "a")
        kw = {"creationflags": 0x08000008 | 0x00000200} if NT else {"start_new_session": True}
        subprocess.Popen([pyw, str(Path(__file__)), "_bg"], cwd=str(root), stdout=log, stderr=log, stdin=subprocess.DEVNULL, **kw)
        time.sleep(2)
        print("Son of Anton is running in the background (tray icon). `python run.py open` for the dashboard, `stop` to quit.")
    elif cmd == "stop":
        pid = running()
        if not pid:
            return print("Not running.")
        if NT:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                os.kill(pid, signal.SIGTERM)
        PID.unlink(missing_ok=True)
        print("Stopped.")
    elif cmd == "status":
        print("running (pid %s)" % running() if running() else "not running")
    elif cmd == "logs":
        p = data / "soa.log"
        print("".join(p.read_text(errors="replace").splitlines(True)[-60:]) if p.exists() else "no log yet")
    elif cmd == "open":
        tok = (data / "token").read_text().strip() if (data / "token").exists() else ""
        webbrowser.open(f"http://localhost:8765/?token={tok}")
    elif cmd == "update":
        sys.path.insert(0, str(root))
        from soa import config, updater
        cfg = config.load()
        r = updater.check(cfg)
        print(r["msg"])
        if r.get("available"):
            print(updater.apply(cfg)[1])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
