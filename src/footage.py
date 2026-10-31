"""Build the background montage: free stock clips (Pixabay or Pexels), cut every few seconds, slow zoom.

Clips are downloaded once into assets/clips/ and reused. Only FFmpeg is used for editing.
"""
import json
import math
import random
import os
import subprocess
import time
import urllib.parse
import urllib.request

from common import ROOT, find_ffmpeg, load_config, load_env, load_json, save_json

CLIPS = ROOT / "assets" / "clips"
SEARCH_CACHE = ROOT / "assets" / "search_cache.json"
BRIGHTNESS_CACHE = ROOT / "assets" / "clips" / "brightness.json"
CUTS_PER_CLIP = 2  # each downloaded clip gives 2 different cuts (fewer downloads)
MAX_DOWNLOAD_MB = 40
KEEP_CLIPS_DAYS = 30
W, H, FPS = 1080, 1920, 30
HEADERS = {"User-Agent": "alpha-mindset-shorts"}
# Wikimedia asks every automated tool to name itself in the User-Agent
COMMONS_HEADERS = {"User-Agent": "AlphaMindsetBot/1.0 (automated short-video maker)"}


def env_key(name):
    load_env()
    key = os.environ.get(name, "").strip()
    return "" if key.startswith("paste") else key


def get_json(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers={**HEADERS, **(headers or {})}),
                                timeout=60) as resp:
        return json.load(resp)


def search_pixabay(query, key):
    data = get_json("https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": key, "q": query, "video_type": "film", "safesearch": "true", "per_page": 20}))
    found = []
    for hit in data.get("hits", []):
        # prefer 4K (sharp after cropping to vertical) unless the file is very big
        for size in ("large", "medium"):
            f = hit["videos"].get(size) or {}
            if f.get("url") and f.get("size", 0) <= MAX_DOWNLOAD_MB * 1e6:
                found.append({"id": f"pixabay_{hit['id']}", "duration": hit.get("duration", 0),
                              "url": f["url"], "height": f.get("height", 0), "tags": hit.get("tags", "")})
                break
    return found


def search_pexels(query, key):
    data = get_json("https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "portrait", "size": "medium", "per_page": 15}),
        {"Authorization": key})
    found = []
    for video in data.get("videos", []):
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")
                 and f["height"] > f["width"] and f["height"] >= 1280]
        best = min(files, key=lambda f: abs(f["height"] - 1920), default=None)
        if best:
            found.append({"id": f"pexels_{video['id']}", "duration": video.get("duration", 0),
                          "url": best["link"], "height": best["height"]})
    return found


def provider():
    if env_key("PIXABAY_API_KEY"):
        return "pixabay", env_key("PIXABAY_API_KEY")
    if env_key("PEXELS_API_KEY"):
        return "pexels", env_key("PEXELS_API_KEY")
    return None, ""


def search(query, name, key):
    """Search with a 24-hour cache (required by Pixabay's terms, and saves requests)."""
    cache = load_json(SEARCH_CACHE, {})
    entry = cache.get(f"{name}:{query}")
    if entry and time.time() - entry["time"] < 24 * 3600:
        return entry["results"]
    results = (search_pixabay if name == "pixabay" else search_pexels)(query, key)
    cache[f"{name}:{query}"] = {"time": time.time(), "results": results}
    SEARCH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    save_json(SEARCH_CACHE, cache)
    return results


def search_paintings(query):
    """Public-domain artworks on Wikimedia Commons for a search like 'Caravaggio Taking of Christ'.

    Only files marked public domain are kept (old paintings: free to use, no credit required),
    big enough to stay sharp in a vertical video. Cached for 7 days.
    """
    cache = load_json(SEARCH_CACHE, {})
    entry = cache.get(f"commons:{query}")
    if entry and time.time() - entry["time"] < 7 * 24 * 3600:
        return entry["results"]
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
         "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": 8, "prop": "imageinfo",
         "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 2400})
    for attempt in range(4):  # Wikimedia answers 429 "too many requests" when called too fast: wait and retry
        try:
            data = get_json(url, COMMONS_HEADERS)
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 0) or 15 * (attempt + 1))
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    found = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license = (meta.get("License", {}).get("value", "") + " " +
                   meta.get("LicenseShortName", {}).get("value", "")).lower()
        if not ("public domain" in license or license.startswith("pd")):
            continue
        width, height = info.get("width", 0), info.get("height", 0)
        if info.get("mime") not in ("image/jpeg", "image/png") or min(width, height) < 900:
            continue
        if max(width, height) > 2.5 * min(width, height):  # long scrolls and panoramas don't fit a vertical video
            continue
        found.append({"id": f"commons_{page['pageid']}", "url": info.get("thumburl") or info["url"],
                      "title": page.get("title", ""), "width": info["width"], "height": info["height"]})
    cache[f"commons:{query}"] = {"time": time.time(), "results": found}
    SEARCH_CACHE.parent.mkdir(parents=True, exist_ok=True)
    save_json(SEARCH_CACHE, cache)
    return found


def find_paintings(queries):
    """The best public-domain painting for each search (a failed search is skipped).
    Returns a list of (path, width, height)."""
    paintings, used = [], set()
    for n, q in enumerate(queries):
        if n:
            time.sleep(1)  # gentle with Wikimedia's servers
        try:
            hit = next((p for p in search_paintings(q) if p["id"] not in used), None)
            if not hit:
                print(f"No public-domain painting for '{q}'.")
                continue
            used.add(hit["id"])
            paintings.append((download(hit, ext=".jpg", headers=COMMONS_HEADERS), hit["width"], hit["height"]))
        except Exception as e:
            print(f"Painting search '{q}' failed ({type(e).__name__}), skipping it.")
    return paintings


def clean_old_clips():
    """Delete clips not used for KEEP_CLIPS_DAYS days, so the folder doesn't keep growing."""
    if not CLIPS.exists():
        return
    limit = time.time() - KEEP_CLIPS_DAYS * 24 * 3600
    for path in [*CLIPS.glob("*.mp4"), *CLIPS.glob("*.jpg")]:
        if path.stat().st_mtime < limit:
            path.unlink()


def download(clip, ext=".mp4", headers=None):
    CLIPS.mkdir(parents=True, exist_ok=True)
    path = CLIPS / f"{clip['id']}{ext}"
    if path.exists():
        os.utime(path)  # mark as recently used so the cleanup keeps it
    else:
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(urllib.request.Request(clip["url"], headers=headers or HEADERS), timeout=600) as resp, \
                open(tmp, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
        tmp.rename(path)
    return path


def find_clips(keywords, needed):
    """Return up to `needed` (path, duration) clips, taking the fact's keywords in turn.

    A search or download that fails (network, rate limit) is skipped instead of stopping the video.
    """
    name, key = provider()
    subject = subject_root(keywords)
    results = {}
    for q in keywords:
        try:
            found = [c for c in search(q, name, key) if c["duration"] >= 4]
            # best: tags mention every important word; if that leaves too few, accept any of them
            strict = [c for c in found if relevant(c, q, strict=True)]
            results[q] = strict if len(strict) >= 3 else [c for c in found if relevant(c, q, subject=subject)]
        except Exception as e:
            print(f"Clip search '{q}' failed ({type(e).__name__}), skipping it.")
            results[q] = []
    clips, used = [], set()
    while len(clips) < needed and any(results.values()):
        for q in keywords:
            while results[q]:
                clip = results[q].pop(0)
                if clip["id"] in used:
                    continue
                used.add(clip["id"])
                try:
                    path = download(clip)
                except Exception as e:
                    print(f"Clip download failed ({type(e).__name__}), trying another one.")
                    continue
                if too_dark(path):
                    continue
                clips.append((path, clip["duration"]))
                break
            if len(clips) >= needed:
                break
    return clips


# clips that look out of place on a real-facts channel (fair rides named "Octopus", cartoons, logos...)
OFF_TOPIC_TAGS = {"carousel", "fairground", "fair", "funfair", "amusement park", "ride", "cartoon", "animation",
                  "animated", "illustration", "logo", "toy", "toys", "anime", "clipart", "emoji",
                  "makeup", "make-up", "fashion", "model", "beauty", "glamour", "cosmetics", "portrait",
                  # things that break a serious motivation mood (phones, cars, offices and cities are on-topic here)
                  "bitcoin", "crypto", "cryptocurrency", "blockchain", "btc", "ethereum", "nightclub",
                  "party", "halloween", "selfie", "christmas", "santa", "birthday", "wedding", "bikini",
                  "funny", "cute", "baby", "kitten", "puppy",
                  # footage made for video editing, not to be shown as is (a man on a green screen slipped through once)
                  "green screen", "greenscreen", "chroma key", "chromakey", "chroma", "green background",
                  "alpha channel", "transparent background", "blue screen"}

PERSON_TAGS = {"woman", "women", "man", "men", "girl", "girls", "boy", "boys", "kid", "kids", "child", "children",
               "people", "person", "lady", "guy", "couple", "family", "baby", "teenager", "human", "face"}

STOP_WORDS = {"with", "from", "into", "under", "over", "slow", "motion", "close", "macro", "time", "lapse",
              "timelapse", "aerial", "view", "the", "and"}


def relevant(clip, query, strict=False, subject=""):
    """Keep a clip only if its tags mention the words of the search (e.g. 'cocoa' for 'cocoa beans'),
    so a search does not return soy beans. strict=True needs every word. Clips without tags are kept."""
    tags = clip.get("tags")
    if not tags:
        return True
    tag_list = [t.strip() for t in tags.lower().split(",")]
    tags = ", ".join(tag_list)
    if set(tag_list) & OFF_TOPIC_TAGS:
        return False
    # the first tag is the clip's main subject: skip clips about a person unless the search asks for people
    if tag_list and tag_list[0] in PERSON_TAGS and not set(query.lower().split()) & PERSON_TAGS:
        return False
    roots = word_roots(query)
    if not roots:
        return True
    if strict:
        return all(r in tags for r in roots)
    # loose: the video's subject must be there ('melted chocolate' needs chocolate, not just melting ice),
    # or the first word when the search doesn't name the subject ('cocoa beans' needs cocoa)
    return (subject if subject in roots else roots[0]) in tags


def word_roots(text):
    """First 4 letters of each meaningful word, so 'melted' matches 'melting' and 'beans' matches 'bean'."""
    return [w[:4] for w in text.lower().split() if len(w) > 2 and w not in STOP_WORDS]


def subject_root(keywords):
    """The video's subject: the word root that comes back most often in its search words."""
    roots = [r for k in keywords for r in word_roots(k)]
    return max(roots, key=roots.count) if roots else ""


def too_dark(path, limit=40):
    """True if the clip is mostly black (night shots look empty behind the captions). Result is cached."""
    cache = load_json(BRIGHTNESS_CACHE, {})
    if path.name not in cache:
        frame = subprocess.run([find_ffmpeg(), "-v", "error", "-ss", "1.5", "-i", str(path), "-frames:v", "1",
                                "-vf", "scale=16:16,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        cache[path.name] = round(sum(frame) / len(frame), 1) if frame else 255
        save_json(BRIGHTNESS_CACHE, cache)
    if cache[path.name] < limit:
        print(f"Skipping a very dark clip ({path.name}).")
        return True
    return False


def build_background(keywords, durations, out_mp4, seed="", paintings=()):
    """Make a silent 1080x1920 montage from shots of the given `durations` (seconds).

    Every shot gets its own camera move (zooms, pans, punch-in, tilt, handheld) and about one in four
    is in slow motion, so the background never feels static or repetitive.
    `paintings` are Wikimedia Commons searches: the first shot and about one shot in three then show
    a famous public-domain painting with a slow zoom or pan. With "crossfade_seconds" in the style,
    shots blend into each other instead of cutting.
    Returns False if no stock-video key is set or no clip can be used.
    """
    name, _ = provider()
    if not name:
        print("No PIXABAY_API_KEY or PEXELS_API_KEY in .env: using the plain animated background.")
        return False
    clean_old_clips()
    count = len(durations)
    seconds = sum(durations)
    art = find_paintings(paintings) if paintings else []
    art_shots = {i for i in range(count) if art and i % PAINTING_EVERY == 0}
    clips = find_clips(keywords, math.ceil((count - len(art_shots)) / CUTS_PER_CLIP))
    if not clips and art:  # paintings alone are better than the plain background
        art_shots = set(range(count))
    elif not clips:
        print("No stock clips found: using the plain animated background.")
        return False

    rng = random.Random(f"{seed}-montage")
    ffmpeg = find_ffmpeg()
    parts, previous, video_i, art_i, stills = [], None, 0, 0, {}
    for i, shot in enumerate(durations):
        # every shot but the last is a bit longer: that extra part is where it blends into the next one
        length = shot + (CROSSFADE if i < count - 1 else 0)
        part = out_mp4.parent / f"part{i:02d}.mp4"
        if i in art_shots:
            path, width, height = art[(art_i // CUTS_PER_CLIP) % len(art)]
            move = rng.choice([m for m in ["zoom_in", "zoom_out"] if m != previous] or ["zoom_in"])
            previous, art_i = move, art_i + 1
            if path not in stills:  # the painting doesn't move: grade, blur and frame it once, then only zoom
                stills[path] = painting_still(path, width, height, out_mp4.parent / f"still{len(stills)}.png")
            done = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS),
                                   "-t", f"{length:.3f}", "-i", str(stills[path]),
                                   "-vf", slow_zoom(move, length), "-t", f"{length:.3f}", "-an", *FAST_ENCODE,
                                   str(part)]) if stills[path] else None
            if done and done.returncode == 0 and part.exists():
                parts.append(part)
                continue
            print(f"Broken painting {path.name}, using a video clip instead.")
        move = MOVES[0] if i == 0 else rng.choice([m for m in MOVES if m != previous])
        previous = move
        speed = SLOW_MOTION if i >= 2 and rng.random() < SLOW_MOTION_SHARE else 1.0
        vf = camera_move(move, length, speed)
        # if a clip is broken, delete it and use the next one instead
        for attempt in range(len(clips)):
            path, duration = clips[(video_i // CUTS_PER_CLIP + attempt) % len(clips)]
            need = length * speed  # source seconds used (less in slow motion)
            # 1st shot skips the first second (often a fade-in); 2nd shot takes a later moment of the same clip
            start = 1.0 + (video_i % CUTS_PER_CLIP) * 3.5
            start = min(start, max(0.0, duration - need - 0.2))
            done = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{need:.3f}",
                                   "-i", str(path), "-vf", vf, "-t", f"{length:.3f}", "-an", *FAST_ENCODE,
                                   str(part)])
            if done.returncode == 0 and part.exists():
                break
            print(f"Broken clip {path.name}, using another one.")
            path.unlink(missing_ok=True)
        else:
            print("No usable clips: using the plain animated background.")
            for p in parts:
                p.unlink(missing_ok=True)
            return False
        video_i += 1
        parts.append(part)

    join_parts(parts, durations, seconds, out_mp4)
    for p in [*parts, *(s for s in stills.values() if s)]:
        p.unlink()
    print(f"Montage: {count} shots from {len(clips)} {name} clips and {len(art)} paintings")
    return True


def join_parts(parts, durations, seconds, out_mp4):
    """Put the shots end to end: a soft crossfade between shots, or plain cuts if crossfade_seconds is 0.
    Each crossfade starts exactly where the next shot was planned, so new facts still start on a new shot."""
    ffmpeg = find_ffmpeg()
    if CROSSFADE <= 0 or len(parts) < 2:
        concat_list = out_mp4.parent / "parts.txt"
        concat_list.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                        "-t", f"{seconds:.2f}", "-c", "copy", str(out_mp4)], check=True)
        concat_list.unlink()
        return
    chain, last, offset = [], "[0:v]", 0.0
    for k in range(1, len(parts)):
        offset += durations[k - 1]
        out = f"[x{k}]" if k < len(parts) - 1 else "[v]"
        chain.append(f"{last}[{k}:v]xfade=transition=fade:duration={CROSSFADE}:offset={offset:.3f}{out}")
        last = out
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for p in parts:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", ";".join(chain), "-map", "[v]", "-t", f"{seconds:.2f}", "-an",
            *FAST_ENCODE, str(out_mp4)]
    subprocess.run(cmd, check=True)


STYLE = (load_config() or {}).get("style", {})  # look of the channel, see "style" in config.json
MOVES = STYLE.get("moves", ["zoom_in", "zoom_out", "punch_in", "pan_left", "pan_right", "pan_up", "pan_down", "tilt", "handheld"])
SLOW_MOTION = STYLE.get("slow_motion_speed", 0.75)  # slow-motion shots play the clip at 75% speed
SLOW_MOTION_SHARE = STYLE.get("slow_motion_share", 0.25)  # about one shot in four
GRADE = STYLE.get("grade", "eq=brightness=-0.06:saturation=1.15")
PAINTING_GRADE = STYLE.get("painting_grade", GRADE)  # old paintings are often dark: they can get their own grade
CROSSFADE = STYLE.get("crossfade_seconds", 0)  # 0 = hard cuts
PAINTING_EVERY = STYLE.get("painting_every", 3)  # with paintings: shots 1, 4, 7... show a painting
BW, BH = int(W * 1.2), int(H * 1.2)  # oversized frame, so pans / tilt / shake never show an edge


# intermediate shots are re-encoded once more for the final video: encode them fast, at high quality
FAST_ENCODE = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p"]


def painting_still(path, width, height, out_png):
    """One graded 1080x1920 picture of a painting. Wide paintings are shown whole (cropping them to vertical
    cuts out the main scene) over a blurred, darker copy of themselves; tall ones fill the frame.
    Returns the picture's path, or None if FFmpeg can't read the painting."""
    if width > height * 0.8:
        graph = ["-filter_complex",
                 f"[0:v]{PAINTING_GRADE},split[a][b];"
                 f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:2,"
                 f"eq=brightness=-0.18:saturation=0.8[bg];"
                 f"[b]scale={W - 40}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2"]
    else:
        graph = ["-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},{PAINTING_GRADE}"]
    done = subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-i", str(path), *graph,
                           "-frames:v", "1", str(out_png)])
    return out_png if done.returncode == 0 and out_png.exists() else None


def slow_zoom(move, shot):
    """FFmpeg filter: a slow 8% zoom in or out on a still picture."""
    d = f"{shot:.3f}"
    z = f"(1+0.08*t/{d})" if move == "zoom_in" else f"(1.08-0.08*t/{d})"
    return f"scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame,crop={W}:{H},fps={FPS},setsar=1"


def camera_move(move, shot, speed=1.0, grade=None):
    """FFmpeg filter for one shot: fill the vertical frame, light grade, then a camera move.

    Note: in filter expressions a comma must be written as \\, (it separates filters otherwise).
    """
    d = f"{shot:.3f}"
    head = f"setpts=PTS/{speed}," if speed != 1.0 else ""
    grade = grade or GRADE  # color filters must come before per-frame scaling (eq after it crashes FFmpeg 9.0.2)
    if move in ("zoom_in", "zoom_out", "punch_in"):
        z = {"zoom_in": f"(1+0.12*t/{d})",
             "zoom_out": f"(1.12-0.12*t/{d})",
             "punch_in": "(1+0.12*min(t/0.35\\,1))"}[move]  # quick zoom in the first 0.35 s, then holds
        body = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},{grade},"
                f"scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame,crop={W}:{H}")
    else:
        x, y = "(iw-ow)/2", "(ih-oh)/2"
        rotate = ""
        if move == "pan_left":
            x = f"(iw-ow)*(1-t/{d})"
        elif move == "pan_right":
            x = f"(iw-ow)*t/{d}"
        elif move == "pan_up":
            y = f"(ih-oh)*(1-t/{d})"
        elif move == "pan_down":
            y = f"(ih-oh)*t/{d}"
        elif move == "handheld":  # gentle irregular shake, like a camera held by hand
            x = "(iw-ow)/2+18*sin(2*PI*0.6*t)+7*sin(2*PI*1.7*t)"
            y = "(ih-oh)/2+14*sin(2*PI*0.45*t+1)+6*sin(2*PI*1.3*t)"
        elif move == "tilt":  # slow 1.7 degree rotation
            rotate = f"rotate=a='0.03*t/{d}':ow=iw:oh=ih:c=black,"
        body = (f"scale={BW}:{BH}:force_original_aspect_ratio=increase:flags=lanczos,crop={BW}:{BH},{grade},"
                f"{rotate}crop={W}:{H}:x='{x}':y='{y}'")
    return f"{head}{body},fps={FPS},setsar=1"


def background_frames(bg_mp4):
    """Yield the montage's frames as raw RGB bytes."""
    proc = subprocess.Popen([find_ffmpeg(), "-loglevel", "quiet", "-i", str(bg_mp4),
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = W * H * 3
    last = None
    try:
        while True:
            data = proc.stdout.read(size)
            if len(data) < size:
                break
            last = data
            yield data
        while last:  # if the montage is a frame short, hold the last frame
            yield last
    finally:  # runs when the video is done, even if frames are left over
        proc.kill()
        proc.wait()
        proc.stdout.close()
