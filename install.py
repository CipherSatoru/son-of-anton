"""One-shot installer. Usage: python install.py [--voice] [--autostart]"""
import os, platform, shutil, subprocess, sys, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYS = platform.system()
venv = ROOT / ".venv"
py = venv / ("Scripts/python.exe" if SYS == "Windows" else "bin/python")


def sh(*a, check=True):
    print("$", " ".join(map(str, a)))
    return subprocess.run(list(map(str, a)), check=check).returncode


def main():
    if sys.version_info < (3, 9):
        sys.exit("Need Python 3.9+")
    if not py.exists():
        sh(sys.executable, "-m", "venv", venv)
    sh(py, "-m", "pip", "install", "-q", "--upgrade", "pip")
    sh(py, "-m", "pip", "install", "-q", "-r", ROOT / "requirements.txt")
    if SYS == "Linux":
        print("Linux tip: sudo apt install python3-tk scrot xprintidle xdotool  (mouse/keyboard/screenshot/idle support)")

    env = ROOT / ".env"
    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
        if sys.stdin.isatty():
            print("\nPaste free API keys (Enter to skip any):")
            lines = []
            for k in ("KILO_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY"):
                lines.append(f"{k}={input(k + ': ').strip()}")
            env.write_text("\n".join(lines) + "\n")

    # local brain (Ollama)
    if not shutil.which("ollama"):
        if SYS == "Windows" and shutil.which("winget"):
            sh("winget", "install", "-e", "--id", "Ollama.Ollama", "--accept-source-agreements", "--accept-package-agreements", check=False)
        elif SYS == "Linux":
            sh("sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh", check=False)
        else:
            print("Install Ollama from https://ollama.com/download then run: ollama pull qwen2.5:1.5b")
    if shutil.which("ollama"):
        sh("ollama", "pull", "qwen2.5:1.5b", check=False)

    if "--voice" in sys.argv:
        sh(py, "-m", "pip", "install", "-q", "-r", ROOT / "requirements-voice.txt", check=False)
        d = ROOT / "data"
        d.mkdir(exist_ok=True)
        if not (d / "vosk").exists():
            z = d / "vosk.zip"
            print("Downloading offline speech model (~40MB)...")
            urllib.request.urlretrieve("https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip", z)
            with zipfile.ZipFile(z) as f:
                f.extractall(d)
            (d / "vosk-model-small-en-us-0.15").rename(d / "vosk")
            z.unlink()
        print('Offline PC mic ready: set  "pc_mic": true  in config.json')

    if "--autostart" in sys.argv:
        cmd = f'"{py}" "{ROOT / "run.py"}" bg'
        if SYS == "Windows":
            p = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/son_of_anton.bat"
            p.write_text(f'@echo off\ncd /d "{ROOT}"\nstart "" /min {cmd}\n')
        elif SYS == "Linux":
            p = Path.home() / ".config/autostart/son_of_anton.desktop"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"[Desktop Entry]\nType=Application\nName=Son of Anton\nExec={cmd}\nPath={ROOT}\n")
        print("Autostart enabled:", p)

    sh(py, ROOT / "tests" / "test_core.py", check=False)
    print("\nDone.\n  python run.py        -> run now\n  python run.py bg     -> run hidden in background (tray icon)\n  python run.py update -> pull latest from GitHub")


main()
