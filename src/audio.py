"""Music choice and the final sound mix: voice on top, music ducked under it, a bass hit on each punch card.

pick_music / music_rotation / full_sound_from / track_seconds come unchanged from the other channels:
a track whose mood fits the topic's category, never the same track twice in a row, started after its quiet intro.
New here: the mix is measured line by line and the music is lowered until the voice is at least
VOICE_ABOVE_MUSIC dB louder on every line (the owner heard the music cover the voice on a test video).
"""
import random
import re
import subprocess
from pathlib import Path

from common import ROOT, find_ffmpeg, load_json, save_json

MUSIC_DIR = ROOT / "assets" / "music"
SFX_DIR = ROOT / "assets" / "sfx"
VOICE_ABOVE_MUSIC = 12.0  # dB, on every line
FINAL_LUFS = -14


def track_seconds(path):
    probe = Path(find_ffmpeg()).with_name("ffprobe" + Path(find_ffmpeg()).suffix)
    out = subprocess.run([str(probe), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def full_sound_from(path):
    """Second at which the track reaches its normal loudness (end of the quiet intro). Cached."""
    cache_file = MUSIC_DIR / "analysis.json"
    cache = load_json(cache_file, {})
    if path.name not in cache:
        log = subprocess.run([find_ffmpeg(), "-v", "verbose", "-nostats", "-i", str(path), "-af",
                              "ebur128=framelog=verbose", "-f", "null", "-"], capture_output=True, text=True).stderr
        points = [(float(t), float(s)) for t, s in re.findall(r"t:\s*([\d.]+)\s.*?S:\s*(-?[\d.]+)", log)]
        loud = sorted(s for _, s in points if s > -70)
        typical = loud[len(loud) // 2] if loud else -20
        cache[path.name] = next((t for t, s in points if t >= 3 and s >= typical - 4), 0.0)
        save_json(cache_file, cache)
    return cache[path.name]


def music_rotation(topic, index, tracks, topics, moods):
    """The tracks whose mood fits the topic's category (assets/music/moods.json), and how many videos of
    that mood came before it: the n-th video of a mood gets the n-th track, so tracks alternate."""
    listed = {f for files in moods.get("moods", {}).values() for f in files}
    mood = moods.get("categories", {}).get(topic.get("category", ""))
    pool = [p for p in tracks if p.name in moods.get("moods", {}).get(mood, []) or p.name not in listed]
    categories = moods.get("categories", {})
    nth = sum(1 for t in topics[:index] if categories.get(t.get("category")) == mood)
    return pool or tracks, nth


def pick_music(topic, index, total):
    """Choose the background music for a topic: a track whose mood fits the topic's category
    (assets/music/moods.json), rotated so neighbouring videos don't share a track, long enough
    for the whole video, and started after its quiet intro at a point that changes every video.
    Returns (path, start second) or None if there is no music."""
    tracks = sorted(p for p in MUSIC_DIR.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg"))
    tracks = [p for p in tracks if track_seconds(p) >= total + 1] or tracks
    if not tracks:
        return None
    topics = load_json(ROOT / "topics.json")
    moods = load_json(MUSIC_DIR / "moods.json", {})
    # a track can belong to several moods: replay the choices from the first video so that
    # no video ever gets the same track as the video just before it
    path = None
    for i in range(index + 1):
        pool, nth = music_rotation(topic if i == index else topics[i], i, tracks, topics, moods)
        choice = pool[nth % len(pool)]
        if choice == path and len(pool) > 1:
            choice = pool[(nth + 1) % len(pool)]
        path = choice
    rng = random.Random(f"{topic['id']}-music")
    earliest = max(8.0, full_sound_from(path))
    latest = track_seconds(path) - total - 2
    start = rng.uniform(earliest, latest) if latest > earliest else min(earliest, max(0.0, latest))
    return path, round(start, 2)


def music_credit(path):
    """Credit line a track needs (CC BY tracks), from assets/music/moods.json → credits. Pixabay tracks need none."""
    return load_json(MUSIC_DIR / "moods.json", {}).get("credits", {}).get(path.name, "")


def lufs(path, start=None, end=None, volume=1.0):
    """Integrated loudness of a file or of one part of it."""
    cut = ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"] if start is not None else []
    log = subprocess.run([find_ffmpeg(), "-hide_banner", *cut, "-i", str(path), "-af", f"volume={volume},ebur128",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", log[log.rfind("Summary"):])
    return float(found[0]) if found else -70.0


def ffmpeg(*args):
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", *args], check=True)


def ducked_music(music, voice_wav, total, out):
    """The chosen track from its start point, quiet (-24 LUFS), faded, and pushed down whenever the voice speaks."""
    path, start = music
    ffmpeg("-i", str(path), "-i", str(voice_wav), "-filter_complex",
           f"[0]atrim=start={start},asetpts=PTS-STARTPTS,aresample=44100,aformat=channel_layouts=stereo,"
           f"atrim=0:{total},loudnorm=I=-24:TP=-3,aresample=44100,afade=t=in:d=0.3,"
           f"afade=t=out:st={max(0, total - 3):.2f}:d=3,apad,atrim=0:{total}[m];"
           f"[1]aformat=channel_layouts=stereo,apad,atrim=0:{total}[v];"
           "[m][v]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=400[d]",
           "-map", "[d]", "-ar", "44100", str(out))


def mix(voice, music, hit_times, folder):
    """voice.wav + ducked music + bass hits → mix.wav at -14 LUFS. Lowers the music until the voice is at least
    VOICE_ABOVE_MUSIC dB above it on every line. Returns (mix path, worst voice-over-music gap in dB)."""
    total = voice["total"]
    bed = folder / "music.wav"
    music_volume = 1.6
    if music:
        ducked_music(music, voice["wav"], total, bed)
        for _ in range(4):
            gaps = [lufs(voice["wav"], l["start"], l["end"]) - lufs(bed, l["start"], l["end"], music_volume)
                    for l in voice["lines"]]
            worst = min(gaps)
            if worst >= VOICE_ABOVE_MUSIC:
                break
            music_volume *= 10 ** ((worst - VOICE_ABOVE_MUSIC - 1) / 20)  # lower it by the missing dB, plus 1
        print(f"  sound: music x{music_volume:.2f}, voice at least {worst:.1f} dB above it on every line")
    else:
        worst = 99.0
        print("  sound: no music in assets/music")

    hits = sorted(SFX_DIR.glob("impact-*.mp3"))
    inputs = ["-i", str(voice["wav"])] + (["-i", str(bed)] if music else [])
    parts = ["[0]aformat=channel_layouts=stereo[v]"]
    names = ["[v]"]
    if music:
        parts.append(f"[1]volume={music_volume:.3f}[m]")
        names.append("[m]")
    for k, t in enumerate(hit_times if hits else []):
        inputs += ["-i", str(hits[k % len(hits)])]
        idx = len(inputs) // 2 - 1
        parts.append(f"[{idx}]aformat=channel_layouts=stereo,volume=0.5,adelay={round(max(0, t - 0.02) * 1000)}:all=1[h{k}]")
        names.append(f"[h{k}]")
    graph = ";".join(parts) + ";" + "".join(names) + \
        f"amix=inputs={len(names)}:normalize=0,apad=whole_dur={total},atrim=0:{total}," \
        f"loudnorm=I={FINAL_LUFS}:TP=-1.5:LRA=11"
    out = folder / "mix.wav"
    ffmpeg(*inputs, "-filter_complex", graph, "-ar", "48000", "-ac", "2", str(out))
    return out, worst
