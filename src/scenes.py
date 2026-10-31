"""Choose one background clip per scene: the AI cinema library or a real Pixabay video, alternating.

- assets/library/: clips made once on the owner's PC (Z-Image image + DepthFlow 3D motion, 6 s, 1080x1920),
  listed in library.json by category (rain-alone, gym-heavy, lion...). The script writer names a category per line.
- Pixabay: real footage searched with the line's "search" words. The first test showed loose matching is not enough
  ("man pull ups gym" gave hands counting money; "man" matched): generic words don't count, the subject must match.
  Each chosen segment is cut to 1080x1920, given the cinema grade (dark, teal and orange, vignette) so it blends with
  the library, and rejected if it looks empty (a grey frame slipped through once).
- Recently shown clips are skipped (state.json → "recent_clips"), so a viewer doesn't see the same shot twice in a row.
"""
import math
import random
import subprocess

from common import ROOT, STATE_FILE, find_ffmpeg, load_config, load_json, save_json
import footage

LIBRARY = ROOT / "assets" / "library"
RECENT_KEEP = 160   # about 5 days of videos
MAX_SHOT = 5.8      # a library clip lasts 6 s: longer lines get two shots
GENERIC = {"man", "men", "woma", "wome", "guy", "pers", "peop", "male", "huma", "some"}  # word roots that match anything
DEFAULT_GRADE = ("eq=brightness=-0.07:contrast=1.08:saturation=0.8,"
                 "colorbalance=rs=-0.05:bs=0.06:rh=0.06:bh=-0.05,vignette=angle=PI/4")


def library():
    return load_json(LIBRARY / "library.json", {"clips": []})["clips"]


def recent():
    return load_json(STATE_FILE, {}).get("recent_clips", [])


def remember(ids):
    """Called once the video really reached Zernio (make_video saves the ids in info.json)."""
    state = load_json(STATE_FILE, {})
    state["recent_clips"] = (state.get("recent_clips", []) + list(ids))[-RECENT_KEEP:]
    save_json(STATE_FILE, state)


def pick_library(category, rng, avoid):
    """A clip of the category not shown recently; else a fresh clip of a category sharing a tag; else any fresh clip;
    else the category's clip shown longest ago."""
    clips = library()
    if not clips:
        return None
    same = [c for c in clips if c["cat"] == category]
    tags = set(same[0]["tags"]) if same else set()
    for pool in ([c for c in same if c["id"] not in avoid],
                 [c for c in clips if c["id"] not in avoid and tags & set(c["tags"])],
                 [c for c in clips if c["id"] not in avoid]):
        if pool:
            return rng.choice(pool)
    order = recent()
    return min(same or clips, key=lambda c: order.index(c["id"]) if c["id"] in order else -1)


WOMEN = {"woman", "women", "girl", "girls", "lady", "female"}
MEN = {"man", "men", "boy", "guy", "male", "businessman", "athlete", "boxer"}


def match_score(clip, query):
    """2 = the tags hold every specific word of the search, 1 = its subject (first specific word) and at least half
    of them, 0 = no match. Off-topic tags, and women when the search asks for a man, never match."""
    tags = [t.strip() for t in (clip.get("tags") or "").lower().split(",") if t.strip()]
    if not tags or set(tags) & footage.OFF_TOPIC_TAGS:
        return 0
    words = set(query.lower().split())
    if words & {"man", "men"} and set(tags) & WOMEN and not set(tags) & MEN:
        return 0
    text = ", ".join(tags)
    roots = [r for r in footage.word_roots(query) if r not in GENERIC]
    if not roots:
        return 1 if footage.relevant(clip, query) else 0
    found = sum(1 for r in roots if r in text)
    if found == len(roots):
        return 2
    return 1 if roots[0] in text and found >= math.ceil(len(roots) / 2) else 0


def looks_empty(path, at):
    """True if the frame is nearly black or flat (one colour): nothing to see behind the captions."""
    raw = subprocess.run([find_ffmpeg(), "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1",
                          "-vf", "scale=32:32,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    if not raw:
        return True
    mean = sum(raw) / len(raw)
    spread = (sum((p - mean) ** 2 for p in raw) / len(raw)) ** 0.5
    return mean < 30 or spread < 12


def prepare_stock(path, start, seconds, out):
    """Cut the segment, fill 1080x1920, give it the cinema grade. Returns False if FFmpeg failed."""
    grade = load_config().get("style", {}).get("stock_grade", DEFAULT_GRADE)
    result = subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", str(path),
                             "-t", f"{seconds + 0.3:.2f}", "-an", "-vf",
                             f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,{grade}",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)],
                            capture_output=True)
    return result.returncode == 0 and out.exists()


def pick_stock(query, rng, avoid, seconds, work_dir):
    """A real clip for the search words, cut and graded for this shot, not shown recently. None if nothing fits."""
    name, key = footage.provider()
    if not name:  # no PIXABAY_API_KEY: the library does every shot
        return None
    try:
        found = [c for c in footage.search(query, name, key) if c["duration"] >= seconds + 1]
    except Exception as e:  # network, rate limit: the library takes over
        print(f"  stock search '{query}' failed ({type(e).__name__}), using the library")
        return None
    scored = [(match_score(c, query), c) for c in found if c["id"] not in avoid]
    best = max((s for s, _ in scored), default=0)
    if not best:
        return None
    good = [c for s, c in scored if s == best]  # clips matching every word beat partial matches
    rng.shuffle(good)
    for clip in good[:4]:
        try:
            path = footage.download(clip)
        except Exception as e:
            print(f"  stock download failed ({type(e).__name__}), trying another one")
            continue
        start = round(rng.uniform(0.3, max(0.3, clip["duration"] - seconds - 0.5)), 2)
        work_dir.mkdir(parents=True, exist_ok=True)
        out = work_dir / f"{clip['id']}_{start:.0f}.mp4"
        if prepare_stock(path, start, seconds, out) and not looks_empty(out, seconds / 2):
            return {"id": clip["id"], "path": out}
        print(f"  stock clip {clip['id']} looks empty or broken, trying another one")
    return None


def plan_scenes(lines, total, seed, work_dir):
    """One or two shots per line, from its start to the next line's start. Returns a list of
    {id, path, start, dur, media_start, ai, zoom} where ai tells if the clip is AI-made (TikTok label)."""
    style = load_config().get("style", {})
    stock_share = style.get("stock_share", 0.5)
    rng = random.Random(f"{seed}-scenes")
    avoid = set(recent())
    shots, stock_turn = [], 0.0
    for i, line in enumerate(lines):
        start = 0.0 if i == 0 else line["start"]
        end = lines[i + 1]["start"] if i + 1 < len(lines) else total
        pieces = 2 if end - start > MAX_SHOT else 1
        step = (end - start) / pieces
        for p in range(pieces):
            s, e = start + p * step, start + (p + 1) * step
            clip = None
            # the hook stays cinema; then about stock_share of the shots are real footage
            stock_turn += stock_share
            if i > 0 and stock_turn >= 1 and line.get("search"):
                clip = pick_stock(line["search"], rng, avoid, e - s, work_dir)
                if clip:
                    stock_turn -= 1
                    shots.append({"id": clip["id"], "path": clip["path"], "start": round(s, 3), "dur": round(e - s, 3),
                                  "media_start": 0, "ai": False, "zoom": 1.1})
            if not clip:
                lib = pick_library(line.get("scene", ""), rng, avoid)
                if not lib:
                    raise SystemExit("assets/library is empty: copy the clip library into the repository.")
                clip = lib
                shots.append({"id": lib["id"], "path": LIBRARY / f"{lib['id']}.mp4", "start": round(s, 3),
                              "dur": round(e - s, 3), "media_start": 0, "ai": True, "zoom": 1.08})
            avoid.add(clip["id"])
    return shots
