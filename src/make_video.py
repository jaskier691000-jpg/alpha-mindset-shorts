"""Make one Alpha Mindset video: a deep-voice motivational monologue over cinema clips, captioned word by word.

Steps (look and sound validated by the owner on 31 Oct 2026):
1. voice.py   Chatterbox Nano copies the deep reference voice, line by line, each line checked by whisper;
              pauses (then a slightly slower voice) stretch it past TikTok's 1-minute rule.
2. scenes.py  one or two shots per line: the AI cinema library (assets/library) or a real Pixabay clip.
3. audio.py   music chosen by mood, ducked under the voice (voice ≥ 12 dB above it on every line), a bass hit per
              punch card, final mix at -14 LUFS.
4. build_montage.mjs + HyperFrames  white captions with the spoken word in gold, punch cards with a white flash,
              dip-to-black cuts, then the render (Chrome, no graphics card needed).

Usage:
    python src/make_video.py                 # next unused topic
    python src/make_video.py --topic am0001  # a given topic
"""
import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime

from audio import mix, music_credit, pick_music
from common import OUTPUT, ROOT, STATE_FILE, find_ffmpeg, load_config, load_json, save_json
from scenes import plan_scenes
from voice import record_voice

HYPERFRAMES = "hyperframes@0.8.223"  # pinned: a new version can't change the look without a test
FPS = 30


# ---------- choosing the topic ----------

def pick_topic(lang, topic_id=None, exclude=()):
    topics = load_json(ROOT / "topics.json")
    if topic_id:
        return next(t for t in topics if t["id"] == topic_id)
    used = set(load_json(STATE_FILE, {}).get(lang, [])) | set(exclude)
    for topic in topics:  # topics.json is in posting order
        if topic["id"] not in used and lang in topic.get("lines", {}):
            return topic
    raise SystemExit(f"No unused '{lang}' topics left in topics.json. Ask Claude to write the next batch.")


def topic_index(topic_id):
    return next((i for i, t in enumerate(load_json(ROOT / "topics.json")) if t["id"] == topic_id), 0)


def remaining_topics(lang):
    used = set(load_json(STATE_FILE, {}).get(lang, []))
    return sum(1 for t in load_json(ROOT / "topics.json") if t["id"] not in used and lang in t.get("lines", {}))


# ---------- montage ----------

def punch_cards(lines, total):
    """A card on each line that has one, from its start to the next line; the hook's card is there from frame 0."""
    cards = []
    for i, line in enumerate(lines):
        if not line.get("card"):
            continue
        start = 0.0 if i == 0 else line["start"]
        end = (lines[i + 1]["start"] - 0.05) if i + 1 < len(lines) else total
        cards.append({"text": line["card"], "start": round(start, 3), "end": round(end, 3)})
    return cards


def render(project, out_mp4, total):
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("Node.js (npx) is missing: it renders the montage with HyperFrames.")
    env = {**os.environ, "DO_NOT_TRACK": "1"}
    subprocess.run(["node", str(ROOT / "src" / "build_montage.mjs"), str(project)], check=True, env=env)
    result = subprocess.run([npx, "--yes", HYPERFRAMES, "render", "--output", str(out_mp4)], cwd=project, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not out_mp4.exists():
        print(result.stdout[-3000:], result.stderr[-3000:])
        raise SystemExit("HyperFrames could not render the video (see the lines above).")
    # a render that lost frames would freeze or go black: count them
    probe = shutil.which("ffprobe") or str(find_ffmpeg()).replace("ffmpeg", "ffprobe")
    frames = int(subprocess.run([probe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                 "stream=nb_read_frames", "-of", "csv=p=0", str(out_mp4)],
                                capture_output=True, text=True).stdout.strip() or 0)
    if frames < (total - 0.2) * FPS:
        raise SystemExit(f"The render has {frames} frames for {total:.1f}s: some frames are missing.")
    return frames / FPS


def make_video(lang, topic_id=None, exclude=()):
    """Make the video for the next unused topic. The caller marks it as used once it is published."""
    config = load_config()
    lang_cfg = config["languages"][lang]
    topic = pick_topic(lang, topic_id, exclude)
    title = topic["title"][lang]
    lines = topic["lines"][lang]

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    folder = OUTPUT / f"{stamp}_{lang}_{topic['id']}"
    project = folder / "hf"
    (project / "assets" / "clips").mkdir(parents=True, exist_ok=True)
    (project / "assets" / "audio").mkdir(parents=True, exist_ok=True)
    video = folder / "video.mp4"
    print(f"[{lang}] Topic: {topic['id']} - {title}")

    print(f"[{lang}] Recording the voice ({len(lines)} lines)...")
    voice = record_voice(lines, folder / "voice", config.get("min_seconds", 61))
    total = voice["total"]

    print(f"[{lang}] Choosing the clips...")
    shots = plan_scenes(voice["lines"], total, topic["id"], folder / "stock")
    scenes = []
    for k, shot in enumerate(shots):
        name = f"{k:02d}_{shot['id']}.mp4"
        shutil.copy(shot["path"], project / "assets" / "clips" / name)
        scenes.append({"id": shot["id"], "src": f"assets/clips/{name}", "start": shot["start"], "dur": shot["dur"],
                       "media_start": shot["media_start"], "zoom": shot["zoom"]})
    ai_shots = sum(1 for s in shots if s["ai"])
    print(f"[{lang}] {len(shots)} shots: {ai_shots} from the AI library, {len(shots) - ai_shots} real Pixabay clips")

    print(f"[{lang}] Mixing the sound...")
    cards = punch_cards(voice["lines"], total)
    music = pick_music(topic, topic_index(topic["id"]), total)
    mix_wav, worst = mix(voice, music, [c["start"] for c in cards if c["start"] > 0], folder)
    shutil.copy(mix_wav, project / "assets" / "audio" / "mix.wav")

    words = [w for line in voice["lines"] for w in line["words"]]
    plan = {"total": total, "highlight": config.get("style", {}).get("highlight_hex", "#f5c518"), "scenes": scenes,
            "words": words, "cards": cards, "audio": "assets/audio/mix.wav"}
    (project / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    print(f"[{lang}] Rendering ({len(words)} words, {total:.1f}s)...")
    seconds = render(project, video, total)
    # copies of clips and audio and the graded stock cuts: the video has them now
    shutil.rmtree(project / "assets", ignore_errors=True)
    shutil.rmtree(folder / "stock", ignore_errors=True)

    # caption: the hook, the topic's searchable sentence, a comment prompt, a credit if the track needs one,
    # then the topic's 4 hashtags + the account's own (Instagram allows 5)
    credit = music_credit(music[0]) if music else ""
    hashtags = f"{topic.get('hashtags', {}).get(lang, '')} {lang_cfg['hashtags']}".strip()
    parts = [f"{lines[0]['text']} {lang_cfg.get('caption_emoji', '')}".strip(),
             topic.get("caption", {}).get(lang, ""), lang_cfg.get("comment_prompt", "")]
    caption = "\n".join(p for p in parts if p)
    if credit:
        caption += f"\n🎵 {credit}"
    caption += f"\n\n{hashtags}"
    info = {"lang": lang, "topic_id": topic["id"], "title": title, "video": str(video), "caption": caption,
            "seconds": round(seconds, 1), "ai_generated": ai_shots > 0, "clips": [s["id"] for s in shots],
            "voice_above_music_db": round(worst, 1)}
    save_json(folder / "info.json", info)
    left = remaining_topics(lang) - len(exclude) - 1
    print(f"[{lang}] Done: {video} ({seconds:.1f}s). Topics left: {left}")
    if left <= 14:
        print(f"[{lang}] WARNING: only {left} topics left (about {left // 2} days). Ask Claude for the next batch.")
    return info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en")
    parser.add_argument("--topic", help="topic id from topics.json (default: next unused)")
    args = parser.parse_args()
    make_video(args.lang, args.topic)


if __name__ == "__main__":
    main()
