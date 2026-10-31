"""Shared helpers: paths, config, .env loading, finding ffmpeg."""
import glob
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
STATE_FILE = ROOT / "state.json"


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config():
    return load_json(ROOT / "config.json")


def load_env():
    """Read KEY=value lines from .env into os.environ (without overwriting)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    # winget installs FFmpeg here; the PATH change only applies to new terminals
    pattern = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe"
    )
    matches = glob.glob(pattern)
    if matches:
        return matches[0]
    raise SystemExit("FFmpeg not found. Install it with: winget install Gyan.FFmpeg")
