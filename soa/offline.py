"""Background setup of everything needed to work with NO internet: offline mic (Vosk), offline voice (Piper), local brain (Ollama).
Runs once while you're online; skips whatever is already there."""
import asyncio, importlib, os, shutil, subprocess, sys, urllib.request, zipfile
from . import config
from .llm import _ollama

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/"
PIPER_FILES = ("en_GB-alan-medium.onnx", "en_GB-alan-medium.onnx.json")
PKGS = (("vosk", "vosk"), ("sounddevice", "sounddevice"), ("pyttsx3", "pyttsx3"), ("piper", "piper-tts"))


def _get(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def ensure_sync(log=print):
    d = config.DATA
    for mod, pkg in PKGS:
        try:
            importlib.import_module(mod)
        except Exception:
            log(f"offline setup: installing {pkg}...")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], timeout=900, capture_output=True)
            except Exception as e:
                log(f"offline setup: {pkg} failed ({type(e).__name__})")
    p = d / "piper"
    p.mkdir(exist_ok=True)
    for f in PIPER_FILES:
        if not (p / f).exists():
            try:
                log(f"offline setup: downloading voice {f}...")
                _get(PIPER + f, p / f)
            except Exception as e:
                log(f"offline setup: voice download failed ({type(e).__name__})")
    if not (d / "vosk").exists():
        try:
            log("offline setup: downloading offline speech model (~40MB)...")
            z = d / "vosk.zip"
            _get(VOSK_URL, z)
            with zipfile.ZipFile(z) as f:
                f.extractall(d)
            (d / "vosk-model-small-en-us-0.15").rename(d / "vosk")
            z.unlink()
        except Exception as e:
            log(f"offline setup: speech model failed ({type(e).__name__})")
    if not _ollama() and os.name == "nt" and shutil.which("winget"):
        log("offline setup: installing local brain (Ollama)...")
        try:
            subprocess.run(["winget", "install", "-e", "--id", "Ollama.Ollama", "--silent", "--accept-source-agreements",
                            "--accept-package-agreements"], timeout=1200, capture_output=True)
        except Exception as e:
            log(f"offline setup: Ollama install failed ({type(e).__name__})")
    log("offline setup: done")


async def ensure(log=print):
    try:
        await asyncio.get_running_loop().run_in_executor(None, ensure_sync, log)
    except Exception as e:
        log(f"offline setup error: {e}")
