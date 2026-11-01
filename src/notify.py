"""Telegram alerts: a message when videos are scheduled, when they go live, and when something fails.

Needs TELEGRAM_BOT_TOKEN (in .env on the PC, as a Secret on GitHub) and "telegram_chat_id" in config.json.
If they are missing, nothing is sent and nothing breaks. A failed message never stops the videos.

Usage:
    python src/notify.py test            # send a test message
    python src/notify.py check           # tell Telegram which scheduled posts went live (or failed)
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from common import ROOT, STATE_FILE, load_config, load_env, load_json, save_json

# posts already reported, kept apart from state.json so the two GitHub jobs never edit the same file
NOTIFIED_FILE = ROOT / "notified.json"


def send(text):
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    # the chat id is not a secret (nobody can message you without the token), so it lives in config.json
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or str(load_config().get("telegram_chat_id", "")).strip()
    if not token or token.startswith("paste") or not chat:
        return False
    # one bot can serve several channels: every message says which channel it is about
    name = str(load_config().get("channel_name", "")).strip()
    if name:
        text = f"{load_config().get('telegram_emoji', '')} {name.upper()}{chr(10)}{text}".strip()
    body = {"chat_id": chat, "text": text, "disable_web_page_preview": True}
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except Exception as e:  # an alert must never break the video job
        print(f"Telegram message not sent ({type(e).__name__}).")
        return False


def check_live_posts():
    """For each scheduled post whose time has passed: tell Telegram once if it is live or failed."""
    from publish import api  # needs the Zernio key, only loaded when checking

    config = load_config()
    state = load_json(STATE_FILE, {})  # read only: the video job owns state.json
    done = load_json(NOTIFIED_FILE, [])
    now = datetime.now(ZoneInfo(config["timezone"])).replace(tzinfo=None)
    changed = False
    for post in state.get("posts", []):
        if post["id"] in done:
            continue
        due = datetime.fromisoformat(post["when"])
        if now < due + timedelta(minutes=5):
            continue
        try:
            _, data = api("GET", f"/posts/{post['id']}")
        except SystemExit as e:
            print(f"Could not check {post['topic']}: {e}")
            continue
        p = data.get("post", data)
        title = post.get("title") or post["topic"].replace("-", " ")
        lines, failed, waiting = [], False, not p.get("platforms")  # no details yet = not confirmed live
        for pl in p.get("platforms", []):
            name = {"tiktok": "TikTok", "instagram": "Instagram"}.get(pl.get("platform"), pl.get("platform"))
            status = (pl.get("status") or "").lower()
            if status == "published":
                lines.append(f"{name}: {pl.get('platformPostUrl') or 'en ligne'}")
            elif status in ("failed", "error", "rejected", "cancelled"):
                failed = True
                lines.append(f"{name}: ÉCHEC ({pl.get('errorMessage') or pl.get('error') or 'raison inconnue'})")
            else:
                waiting = True
                lines.append(f"{name}: en cours ({status or 'inconnu'})")
        if failed:
            send(f"❌ Problème de publication : {title}\n" + "\n".join(lines)
                 + "\n\nOuvre le tableau de bord Zernio : il faut peut-être reconnecter le compte.")
        elif waiting and now < due + timedelta(hours=2):
            continue  # still being published, check again next time
        elif waiting:
            send(f"⚠️ Toujours pas en ligne 2 h après l'heure prévue : {title}\n"
                 + "\n".join(lines) + "\n\nVérifie dans le tableau de bord Zernio.")
        else:
            send(f"✅ Publiée : {title}\n" + "\n".join(lines))
        done.append(post["id"])
        changed = True
    if changed:
        save_json(NOTIFIED_FILE, done[-60:])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "test":
        print("sent" if send("👋 Test : les alertes sont bien branchées.") else "NOT sent (token or chat id missing)")
    else:
        check_live_posts()
