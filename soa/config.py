import copy, json, os, secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
(DATA / "skills").mkdir(exist_ok=True)

DEFAULTS = {
    "name": "Son of Anton",
    "wake_phrase": "son of anton",
    "end_phrase": "over",
    "wake_timeout": 40,
    "host": "0.0.0.0",
    "port": 8765,
    "tls_port": 8766,
    "local": {"enabled": True, "url": "http://127.0.0.1:11434",
              "model": "qwen2.5:1.5b", "keep_alive": "30m"},
    "providers": [
        {"name": "kilo", "base": "https://api.kilo.ai/api/gateway", "key_env": "KILO_API_KEY",
         "models": ["kilo-auto/free"], "discover_free": True},
        {"name": "groq", "base": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
         "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]},
        {"name": "nvidia", "base": "https://integrate.api.nvidia.com/v1", "key_env": "NVIDIA_API_KEY",
         "models": ["meta/llama-3.3-70b-instruct"]},
        {"name": "openrouter", "base": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
         "models": ["meta-llama/llama-3.3-70b-instruct:free"], "discover_free": True},
    ],
    "idle_seconds": 120,
    "self_improve": {"enabled": True, "max_cycles_per_day": 24, "cooldown_seconds": 600},
    "fastpath": {"promote_after": 3, "fuzzy": 0.88},
    "agent_max_steps": 8,
    "allow_dangerous": False,
    "tts": {"voice": "en-GB-RyanNeural", "rate": "+4%"},
    "tts_local": False,
    "auto_finish_seconds": 6,
    "update": {"repo": "CipherSatoru/son-of-anton", "branch": "main", "check_minutes": 30, "auto": True},
    "pc_mic": False,
}


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ[k.strip()] = v.strip().strip("\"'")


def save_env(key, value):
    """Persist a key in .env (never touched by updates)."""
    p = ROOT / ".env"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, done = [], False
    for l in lines:
        if l.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(l)
    if not done:
        out.append(f"{key}={value}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = value


def version():
    try:
        return (ROOT / "VERSION").read_text().strip()
    except Exception:
        return "0"


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v


def load():
    load_env()
    cfg = copy.deepcopy(DEFAULTS)
    p = ROOT / "config.json"
    if p.exists():
        try:
            _merge(cfg, json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            print("config.json ignored:", e)
    return cfg


def token():
    p = DATA / "token"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(16))
    return p.read_text().strip()
