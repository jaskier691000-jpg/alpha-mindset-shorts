"""Full audit of the Alpha Mindset channel (the blueprint's section 7 checklist, adapted to this pipeline).

    python tools/audit.py            # before go-live: the schedule may still be off and publish_mode draft
    python tools/audit.py --go-live  # at go-live: the schedules must be on and publish_mode schedule

Needs: .env (Zernio key) for the account checks, and the GitHub CLI logged in to the channel's account
(GH_TOKEN for jaskier691000-jpg) for the repository checks. Prints every check and ends with the number of problems.
Fix, then run it again from zero until it says 0 problem(s).
"""
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from common import load_env  # noqa: E402

REPO = "jaskier691000-jpg/alpha-mindset-shorts"
GO_LIVE = "--go-live" in sys.argv
problems, notes = [], []


def check(ok, label, detail=""):
    print(f"  {'OK ' if ok else 'XX '} {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        problems.append(label + (f": {detail}" if detail else ""))


def run(*cmd, cwd=ROOT):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def gh_json(*args):
    code, out = run("gh", *args)
    try:
        return json.loads(out) if code == 0 else None
    except json.JSONDecodeError:
        return None


def section(name):
    print(f"\n== {name}")


section("GitHub repository")
repo = gh_json("api", f"repos/{REPO}")
check(bool(repo), "repository reachable with the channel's GitHub account")
if repo:
    check(repo.get("visibility") == "public", "repository is public (unlimited free Actions minutes)", repo.get("visibility"))
secrets = gh_json("api", f"repos/{REPO}/actions/secrets") or {}
names = {s["name"] for s in secrets.get("secrets", [])}
for name in ("ZERNIO_API_KEY", "PIXABAY_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    check(name in names, f"secret {name} is set")
workflows = gh_json("api", f"repos/{REPO}/actions/workflows") or {}
states = {w["path"]: w["state"] for w in workflows.get("workflows", [])}
for wf in (".github/workflows/daily.yml", ".github/workflows/notify.yml"):
    check(states.get(wf) == "active", f"workflow {wf} is active", states.get(wf, "missing"))

section("Workflows")
daily = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
notify = (ROOT / ".github/workflows/notify.yml").read_text(encoding="utf-8")
check("runs-on: ubuntu-24.04" in daily and "runs-on: ubuntu-24.04" in notify, "runners pinned to ubuntu-24.04")
check("ref: main" in daily, "daily job checks out the latest main (backup runs see saved state)")
check(re.search(r"Save which topics.*\n\s+if: always\(\)", daily) is not None, "state is saved even when the job fails")
check("Telegram alert if the job failed" in daily, "Telegram alert when the job breaks")
check("concurrency:" in daily, "one daily job at a time (concurrency)")
check("retention-days: 3" in daily, "videos kept 3 days as artifacts")
crons = re.findall(r"^\s+- cron: \"([^\"]+)\"", daily, re.M)
notify_crons = re.findall(r"^\s+- cron: \"([^\"]+)\"", notify, re.M)
if GO_LIVE:
    check(len(crons) == 2, "daily schedule ON: main run + backup run", f"{len(crons)} active cron(s)")
    check(len(notify_crons) >= 1, "post checks schedule ON", f"{len(notify_crons)} active cron(s)")
else:
    notes.append(f"schedules are {'ON' if crons else 'OFF (by design until go-live)'}")

run_daily_py = (ROOT / "src/run_daily.py").read_text(encoding="utf-8")
notify_py = (ROOT / "src/notify.py").read_text(encoding="utf-8")
first_cron = re.search(r'cron: "([0-9]+) ([0-9]+) \* \* \*"', daily)
check("def make_or_skip" in run_daily_py and "info = make_or_skip(" in run_daily_py,
      "a broken topic is skipped, never blocks the channel")
check("check_today_scheduled()" in notify_py.split("__main__")[-1], "Telegram alert when no video was scheduled today")
check("check_accounts_now()" in notify_py.split("__main__")[-1], "account cut by Meta/TikTok reported within 30 min")
check((ROOT / "constraints.txt").exists() and "-c constraints.txt" in daily, "exact package versions locked (constraints.txt)")
check(bool(first_cron) and int(first_cron.group(2)) <= 3, "daily run starts by 03:00 UTC (GitHub often starts 30-60 min late)")

section("Keys never in the repository")
code, tracked = run("git", "ls-files")
check(".env" not in tracked.split(), ".env is not tracked by git")
check(".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").split(), ".env is in .gitignore")
load_env()
import os  # noqa: E402
values = [os.environ.get(k, "") for k in ("ZERNIO_API_KEY", "PIXABAY_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")]
code, history = run("git", "log", "-p", "--all")
leaked = [v for v in values if v and len(v) > 6 and v in history]
check(not leaked, "no key or chat id anywhere in the git history", f"{len(leaked)} found" if leaked else "")

section("Settings (config.json)")
config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
en = config["languages"]["en"]
expected_mode = "schedule" if GO_LIVE else "draft"
check(config["publish_mode"] == expected_mode, f"publish_mode is '{expected_mode}'", config["publish_mode"])
check(config["timezone"] == "Europe/Paris" and en["post_times"] == ["08:00", "20:00"], "post times 08:00 and 20:00 Paris")
check(config.get("post_time_jitter_minutes") == 35 and config.get("min_seconds") == 61, "±35 min jitter, videos ≥ 61 s")
check(all(en["accounts"].get(p) for p in ("tiktok", "instagram")), "TikTok and Instagram account ids set")
check(not config.get("telegram_chat_id"), "Telegram chat id kept out of the public repository (it is a secret)")
check(config.get("channel_name") == "Alpha Mindset", "channel name set (every Telegram message carries it)")
check(len(en["hashtags"].split()) == 1, "one account hashtag (+ 4 per topic = 5, Instagram's maximum)")

section("Zernio accounts")
try:
    from publish import api  # noqa: E402
    for platform, account in en["accounts"].items():
        _, h = api("GET", f"/accounts/{account}/health")
        token = h.get("tokenStatus") or {}
        can = h.get("permissions", {}).get("canPost", h.get("canPost"))
        check(h.get("status") == "healthy" and can, f"{platform} connected and can post", token.get("expiresIn", ""))
except SystemExit as e:
    check(False, "Zernio reachable with the key in .env", str(e)[:120])

section("Code")
code, out = run(sys.executable, "-m", "py_compile", *[str(p) for p in (ROOT / "src").glob("*.py")], str(Path(__file__)))
check(code == 0, "every Python file compiles", out.strip()[:200])
code, out = run("node", "--check", str(ROOT / "src" / "build_montage.mjs"))
check(code == 0, "montage builder is valid JavaScript", out.strip()[:200])
req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
check("chatterbox-tts @ git+" in req and "@5de7a54" in req, "voice model pinned to the tested Chatterbox commit")
check("hyperframes@0.8.223" in (ROOT / "src" / "make_video.py").read_text(encoding="utf-8"), "HyperFrames version pinned")
daily_py = (ROOT / "src" / "run_daily.py").read_text(encoding="utf-8")
check(re.search(r"^\s+clean_old_clips\(\)", daily_py, re.M) is not None, "old stock clips deleted every run (cache stays small)")

section("Content")
code, out = run(sys.executable, "src/add_content.py")
check(code == 0 and "Short monologues" not in out, "every written monologue passes the checker", out.strip().splitlines()[-1][:160] if out.strip() else "")
plan = json.loads((ROOT / "topic_plan.json").read_text(encoding="utf-8"))
topics = json.loads((ROOT / "topics.json").read_text(encoding="utf-8"))
check(len(plan) == 730 and len({p["id"] for p in plan}) == 730, "yearly plan: 730 different topics")
state = json.loads((ROOT / "state.json").read_text(encoding="utf-8")) if (ROOT / "state.json").exists() else {}
left = [t for t in topics if t["id"] not in set(state.get("en", []))]
check(len(left) >= 60, "at least 30 days of written topics ahead", f"{len(left)} topics = {len(left) // 2} days")
hooks = [t["lines"]["en"][0]["text"].lower() for t in topics]
check(len(hooks) == len(set(hooks)), "no hook used twice")
lines = [l["text"].lower() for t in topics for l in t["lines"]["en"] if len(l["text"].split()) >= 6]
dupes = {l for l in lines if lines.count(l) > 1}
check(not dupes, "no long line repeated across monologues", f"{len(dupes)} repeated" if dupes else "")
start = date.fromisoformat(plan[0]["date"])
notes.append(f"plan starts {start} (build_plan.py START): set it to the real launch day before go-live")

section("AI cinema library")
lib = json.loads((ROOT / "assets/library/library.json").read_text(encoding="utf-8"))
files = {p.stem for p in (ROOT / "assets/library").glob("*.mp4") if not p.stem.startswith("test-")}
listed = {c["id"] for c in lib["clips"]}
check(listed == files, "library.json lists exactly the clips in assets/library", f"{len(listed)} listed, {len(files)} files")
check(all(c["seconds"] >= 5.9 for c in lib["clips"]), "every library clip lasts 6 s")
per_cat = {c["cat"]: 0 for c in lib["categories"]}
for c in lib["clips"]:
    per_cat[c["cat"]] = per_cat.get(c["cat"], 0) + 1
thin = [k for k, v in per_cat.items() if v < 3]
check(not thin, "every scene category has at least 3 clips", ", ".join(thin[:6]))

section("Music and sound")
from audio import track_seconds  # noqa: E402
tracks = [p for p in (ROOT / "assets/music").glob("*.mp3")]
long_tracks = [p for p in tracks if track_seconds(p) >= 80]
check(len(long_tracks) >= 3, "at least 3 music tracks longer than a video", f"{len(long_tracks)} of {len(tracks)}")
moods = json.loads((ROOT / "assets/music/moods.json").read_text(encoding="utf-8"))
check(all((ROOT / "assets/music" / f).exists() for f in moods.get("credits", {})), "every credited track exists")
missing = [f for files_ in moods.get("moods", {}).values() for f in files_ if not (ROOT / "assets/music" / f).exists()]
check(not missing, "moods.json only names existing tracks", ", ".join(missing))
check((ROOT / "assets/voice/deep_ref.wav").exists(), "deep reference voice present")
check(len(list((ROOT / "assets/sfx").glob("impact-*.mp3"))) >= 2, "two bass hits for the punch cards")

section("Last GitHub runs")
runs = gh_json("run", "list", "-R", REPO, "--workflow", "daily.yml", "--limit", "5", "--json", "conclusion,displayTitle,createdAt,event")
last = (runs or [None])[0]
check(bool(last) and last.get("conclusion") == "success", "last daily run succeeded", (last or {}).get("createdAt", "no run"))
caches = gh_json("cache", "list", "-R", REPO, "--limit", "50", "--json", "key,sizeInBytes") or []
biggest = max((c["sizeInBytes"] for c in caches), default=0) / 1e9
check(bool(caches) and biggest < 8, "GitHub cache well under its 10 GB limit", f"biggest entry {biggest:.1f} GB")

print("\nNotes:")
for n in notes:
    print(f"  - {n}")
print(f"\n{len(problems)} problem(s)" + (":" if problems else ""))
for p in problems:
    print(f"  - {p}")
sys.exit(1 if problems else 0)
