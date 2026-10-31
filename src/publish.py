"""Send a finished video to TikTok + Instagram through the Zernio API.

Usage:
    python src/publish.py accounts                       # show your connected accounts and their IDs
    python src/publish.py send output/<folder>           # send using publish_mode from config.json
    python src/publish.py send output/<folder> --when 2026-10-30T08:00
    python src/publish.py send output/<folder> --dry-run # show what would be sent, send nothing

publish_mode in config.json:
    "draft"    -> nothing goes public. TikTok: video lands in your TikTok inbox to finish by hand.
                  Instagram: saved as a draft in your Zernio dashboard.
    "schedule" -> PUBLIC posts at the chosen time on both platforms.
"""
import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from common import load_config, load_env, load_json

API = "https://zernio.com/api/v1"


def api_key():
    load_env()
    key = os.environ.get("ZERNIO_API_KEY", "")
    if not key or key.startswith("paste"):
        raise SystemExit("ZERNIO_API_KEY is missing. Open the .env file and paste your key there (see README).")
    return key


def request(method, url, body=None, headers=None, raw=None, attempts=4):
    """HTTP call with retries on temporary problems (network, 429, 5xx).

    Retrying POST /posts is safe: it carries an Idempotency-Key, so Zernio never creates it twice.
    """
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                text = resp.read().decode() or "{}"
                return resp.status, json.loads(text) if text.strip().startswith(("{", "[")) else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:2000]
            if e.code not in (408, 409, 425, 429, 500, 502, 503, 504) or attempt == attempts:
                raise SystemExit(f"Zernio error {e.code} on {method} {url.split('?')[0]}:\n{detail}")
            problem = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == attempts:
                raise SystemExit(f"Network error on {method} {url.split('?')[0]}: {e}")
            problem = type(e).__name__
        wait = 20 * attempt
        print(f"Temporary problem ({problem}), retrying in {wait}s...")
        time.sleep(wait)


def api(method, path, body=None, extra_headers=None):
    headers = {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    return request(method, API + path, body, headers)


def list_accounts():
    _, data = api("GET", "/accounts")
    accounts = data.get("accounts", data if isinstance(data, list) else [])
    if not accounts:
        print("No connected accounts yet. Connect TikTok and Instagram in the Zernio dashboard first.")
    for acc in accounts:
        name = acc.get("username") or acc.get("displayName") or acc.get("name") or ""
        print(f"{acc.get('platform', '?'):<10} {name:<30} id = {acc.get('_id')}")
    if accounts:
        print("\nPut each id in config.json, under the language of that account (\"accounts\").")


def upload_video(path):
    path = Path(path)
    content_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    size = path.stat().st_size
    _, presign = api("POST", "/media/presign",
                     {"filename": path.name, "contentType": content_type, "size": size})
    presign = presign.get("data", presign)
    print(f"Uploading {path.name} ({size // 1024} KB)...")
    request("PUT", presign["uploadUrl"], raw=path.read_bytes(), headers={"Content-Type": content_type})
    return presign["publicUrl"]


def build_requests(info, video_url, mode, when, config):
    """Return the list of POST /posts bodies for this video."""
    media = [{"url": video_url, "type": "video"}]
    tiktok_settings = {
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "allow_comment": True,
        "allow_duet": True,
        "allow_stitch": True,
        "content_preview_confirmed": True,
        "express_consent_given": True,
    }
    # TikTok requires the "AI-generated" label on realistic AI images (the cinema library clips).
    # Zernio's field is videoMadeWithAi (docs.zernio.com > Create post > TikTokPlatformData), set in config.json.
    ai_field = config.get("tiktok_ai_label_field", "")
    if info.get("ai_generated") and ai_field:
        tiktok_settings[ai_field] = True
    # each language posts to its own accounts (set in config.json)
    lang_accounts = config["languages"][info["lang"]].get("accounts", {})
    accounts = {}
    for platform in config["platforms"]:
        account_id = lang_accounts.get(platform, "").strip()
        if account_id:
            accounts[platform] = account_id
        else:
            print(f"Skipping {platform}: no {info['lang']} {platform} account id in config.json")

    bodies = []
    if mode == "draft":
        if "tiktok" in accounts:  # goes to the TikTok app inbox, not public
            bodies.append({"content": info["caption"], "mediaItems": media, "publishNow": True,
                           "platforms": [{"platform": "tiktok", "accountId": accounts["tiktok"]}],
                           "tiktokSettings": {**tiktok_settings, "draft": True}})
        if "instagram" in accounts:  # Instagram has no API drafts: kept as a Zernio draft
            bodies.append({"content": info["caption"], "mediaItems": media, "isDraft": True,
                           "platforms": [{"platform": "instagram", "accountId": accounts["instagram"]}]})
    elif mode == "schedule":
        platforms = []
        if "tiktok" in accounts:
            platforms.append({"platform": "tiktok", "accountId": accounts["tiktok"]})
        if "instagram" in accounts:
            platforms.append({"platform": "instagram", "accountId": accounts["instagram"],
                              "platformSpecificData": {"shareToFeed": True}})
        if platforms:
            body = {"content": info["caption"], "mediaItems": media, "platforms": platforms,
                    "scheduledFor": when, "timezone": config["timezone"]}
            if "tiktok" in accounts:
                body["tiktokSettings"] = tiktok_settings
            bodies.append(body)
    else:
        raise SystemExit(f"Unknown publish_mode '{mode}' in config.json (use 'draft' or 'schedule').")
    return bodies


def publish(info, when=None, dry_run=False):
    config = load_config()
    load_env()
    mode = config["publish_mode"]
    when = when or info.get("post_time")
    if mode == "schedule" and not when:
        raise SystemExit("publish_mode is 'schedule' but no time was given (--when 2026-10-30T08:00).")

    if not build_requests(info, "https://check", mode, when, config):
        raise SystemExit(f"No {info['lang']} accounts in config.json: nothing can be published.")
    video_url = "https://<uploaded-video-url>" if dry_run else upload_video(info["video"])
    bodies = build_requests(info, video_url, mode, when, config)
    post_ids = []
    for body in bodies:
        names = "+".join(p["platform"] for p in body["platforms"])
        if dry_run:
            print(f"[dry run] would send to {names}:\n{json.dumps(body, ensure_ascii=False, indent=2)}")
            continue
        # same video + same target = same key, so a re-run never creates a duplicate post
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{info['video']}|{names}|{mode}|{when}"))
        try:
            status, result = api("POST", "/posts", body, {"Idempotency-Key": key})
        except SystemExit as e:
            # if Zernio ever refuses the post because of the AI-label field, post without it
            # rather than lose the video, and tell the owner to check the label in the TikTok app
            ai_field = config.get("tiktok_ai_label_field", "")
            refused = str(e).startswith(("Zernio error 400", "Zernio error 422"))
            if not (refused and ai_field and ai_field in body.get("tiktokSettings", {})):
                raise
            body["tiktokSettings"].pop(ai_field)
            print(f"Zernio refused the AI label field '{ai_field}': posting without it.\n{e}")
            import notify
            notify.send(f"⚠️ Zernio a refusé l'étiquette « contenu IA » ({ai_field}) : la vidéo part sans. "
                        "Coche l'étiquette IA dans l'appli TikTok sur cette vidéo, et dis-le à Claude.")
            status, result = api("POST", "/posts", body, {"Idempotency-Key": key + "-no-ai-label"})
        post = result.get("post", result)
        post_id = post.get("_id") or result.get("postId") or post.get("id")
        post_ids.append(post_id)
        label = "draft" if mode == "draft" else f"scheduled for {when} ({config['timezone']})"
        print(f"OK {status}: {names} {label}. Zernio post id: {post_id}")
    if mode == "draft" and not dry_run:
        print("Nothing is public. TikTok: open the TikTok app inbox to finish the post. "
              "Instagram: the draft is in your Zernio dashboard.")
    return post_ids


def post_problems(post_id):
    """Ask Zernio how a post went. Returns (finished, [problems])."""
    _, data = api("GET", f"/posts/{post_id}")
    post = data.get("post", data)
    problems, finished = [], True
    for p in post.get("platforms", []):
        status = (p.get("status") or "").lower()
        if status in ("failed", "error", "rejected", "cancelled"):
            reason = p.get("errorMessage") or p.get("error") or "no reason given"
            problems.append(f"{p.get('platform')}: {status} ({reason})")
        elif status != "published":
            finished = False
    return finished, problems


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Publish a video through Zernio.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("accounts", help="list connected accounts and their IDs")
    send = sub.add_parser("send", help="send one video folder from output/")
    send.add_argument("folder")
    send.add_argument("--when", help="local post time, e.g. 2026-10-30T08:00 (schedule mode)")
    send.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    args = parser.parse_args()

    if args.command == "accounts":
        list_accounts()
    else:
        publish(load_json(Path(args.folder) / "info.json"), args.when, args.dry_run)
