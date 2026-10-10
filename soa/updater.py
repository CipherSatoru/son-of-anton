"""Self-update. The repo is public, so no token is needed: raw VERSION + codeload zip. Falls back to a GITHUB_TOKEN (private repo)
or the gist bundle. Rolls back if the self-test fails."""
import base64, hashlib, io, shutil, subprocess, sys, tempfile, time, zipfile
import os
from pathlib import Path
import httpx
from . import config, net

SKIP = {"data", ".venv", ".env", "config.json", "__pycache__", ".git"}
GIST = "https://gist.githubusercontent.com/CipherSatoru/fd63009f8a4131a5bc6d2c88f1da0f62/raw"


def _hdr(raw=False):
    h = {"Authorization": "Bearer " + os.environ.get("GITHUB_TOKEN", ""), "X-GitHub-Api-Version": "2022-11-28"}
    h["Accept"] = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
    return h


def _v(s):
    return tuple(int(x) for x in "".join(c if c.isdigit() or c == "." else "" for c in s).split(".") if x.isdigit())


def _gist(cfg):
    return cfg["update"].get("gist", GIST).rstrip("/")


def _remote_version(cfg):
    u = cfg["update"]
    last = None
    try:
        return net.get(f"https://raw.githubusercontent.com/{u['repo']}/{u['branch']}/VERSION", timeout=20).strip()
    except Exception as e:
        last = e
    if os.environ.get("GITHUB_TOKEN"):
        try:
            r = httpx.get(f"https://api.github.com/repos/{u['repo']}/contents/VERSION", params={"ref": u["branch"]}, headers=_hdr(True), timeout=20)
            if r.status_code == 200:
                return r.text.strip()
        except Exception as e:
            last = e
    try:
        return net.get(_gist(cfg) + "/VERSION", timeout=20).strip()
    except Exception:
        raise last


def check(cfg):
    try:
        remote, cur = _remote_version(cfg), config.version()
        return {"ok": True, "current": cur, "remote": remote, "available": _v(remote) > _v(cur),
                "msg": f"v{cur}" + (f" -> v{remote} available" if _v(remote) > _v(cur) else " (latest)")}
    except Exception as e:
        return {"ok": False, "msg": f"update check failed: {type(e).__name__} {e}"}


def _copy_tree(src, dst_root, backup):
    changed = []
    for f in src.rglob("*"):
        rel = f.relative_to(src)
        if f.is_dir() or rel.parts[0] in SKIP or "__pycache__" in rel.parts:
            continue
        dst = dst_root / rel
        if dst.exists():
            b = backup / rel
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, b)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        changed.append(rel)
    return changed


def _fetch(cfg, tmp):
    """Download the latest code into tmp, return the folder that holds it."""
    u = cfg["update"]
    try:
        zipfile.ZipFile(io.BytesIO(net.get(f"https://codeload.github.com/{u['repo']}/zip/refs/heads/{u['branch']}", raw=True, timeout=90))).extractall(tmp)
        return next(d for d in tmp.iterdir() if d.is_dir())
    except Exception:
        pass
    if os.environ.get("GITHUB_TOKEN"):
        r = httpx.get(f"https://api.github.com/repos/{u['repo']}/zipball/{u['branch']}", headers=_hdr(), timeout=60, follow_redirects=True)
        if r.status_code == 200:
            zipfile.ZipFile(io.BytesIO(r.content)).extractall(tmp)
            return next(tmp.iterdir())
    zipfile.ZipFile(io.BytesIO(base64.b64decode(net.get(_gist(cfg) + "/soa_bundle.b64", timeout=60).strip()))).extractall(tmp)
    return tmp


def _pip(req):
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)], timeout=900)
    if r.returncode:                      # one bad package must not block the rest
        for line in Path(req).read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", line.strip()], timeout=300)


def apply(cfg, log=print):
    """Download + install the latest version. Returns (ok, message). Caller restarts on ok."""
    root = config.ROOT
    tmp = Path(tempfile.mkdtemp())
    try:
        src = _fetch(cfg, tmp)
    except Exception as e:
        return False, str(e)
    backup = config.DATA / "backup" / time.strftime("%Y%m%d-%H%M%S")
    old_req = hashlib.md5((root / "requirements.txt").read_bytes()).hexdigest() if (root / "requirements.txt").exists() else ""
    changed = _copy_tree(src, root, backup)
    new_req = hashlib.md5((root / "requirements.txt").read_bytes()).hexdigest()
    if new_req != old_req:
        log("installing new dependencies...")
        _pip(root / "requirements.txt")
    t = subprocess.run([sys.executable, str(root / "tests" / "test_core.py")], capture_output=True, text=True, timeout=120, cwd=str(root))
    if t.returncode != 0:
        _copy_tree(backup, root, config.DATA / "backup" / "_discard")
        return False, "update failed self-test, rolled back"
    shutil.rmtree(tmp, ignore_errors=True)
    return True, f"updated {len(changed)} files to v{config.version()}"
