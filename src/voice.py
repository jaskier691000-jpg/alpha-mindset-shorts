"""The channel voice: Chatterbox Nano copying the deep reference voice, checked word by word with whisper.

Validated by the owner on 31 Oct 2026 ("Nano suffit"). Runs on GitHub's servers, which have no graphics card:
Nano was measured at 2.6x slower than real time on a laptop CPU, the full Chatterbox model at 16x.
Every line is heard back by whisper; a line whisper doesn't recognise is generated again with another seed.
"""
import difflib
import json
import os
import re
import subprocess

from common import ROOT, find_ffmpeg

REFERENCE = ROOT / "assets" / "voice" / "deep_ref.wav"  # license-free deep voice (Kokoro am_onyx, pitched down)
SEEDS = (42, 7, 123, 2024, 99, 555)
LEAD_IN = 0.15        # the hook is spoken at once
MATCH_OK = 0.9        # share of the line's words whisper must hear
MATCH_MINIMUM = 0.75  # below this, after every seed, the line is broken: stop rather than post it
MAX_GAP_SCALE = 1.8   # longer dramatic pauses before slowing the voice down
MIN_TEMPO = 0.88      # never slower than this (atempo): Nano at 0.85 started to sound dragged

_models = {}


def models():
    """Load Chatterbox Nano and whisper once per run (the first run downloads them, then GitHub caches them)."""
    if not _models:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        from faster_whisper import WhisperModel
        # CPU like on GitHub; VOICE_DEVICE=cuda only on a PC whose graphics card is free (ComfyUI uses it too)
        device = os.environ.get("VOICE_DEVICE", "cpu")
        _models["tts"] = ChatterboxTurboTTS.from_pretrained(device=device, nano=True)
        _models["whisper"] = WhisperModel("small.en", device="cpu", compute_type="int8")
    return _models["tts"], _models["whisper"]


def words_of(text):
    """Lowercase words without punctuation, with common contractions opened ("nobody's" = "nobody is")."""
    text = text.lower().replace("’", "'")
    text = re.sub(r"\b(\w+)'s\b", r"\1 is", text)
    text = re.sub(r"\b(\w+)'re\b", r"\1 are", text)
    text = re.sub(r"\b(\w+)'ll\b", r"\1 will", text)
    text = re.sub(r"\b(\w+)'ve\b", r"\1 have", text)
    text = re.sub(r"\b(\w+)'m\b", r"\1 am", text)
    text = re.sub(r"\bcan't\b", "can not", text)
    text = re.sub(r"\b(\w+)n't\b", r"\1 not", text)
    return re.findall(r"[a-z0-9]+", text)


def match(script, heard):
    return difflib.SequenceMatcher(None, words_of(script), words_of(heard)).ratio()


def say(text, seed, wav_path):
    """One take of one line, leading and trailing silence cut. Returns its length in seconds."""
    import librosa
    import torch
    import torchaudio
    tts, _ = models()
    torch.manual_seed(seed)
    wav = tts.generate(text, audio_prompt_path=str(REFERENCE))
    audio, _ = librosa.effects.trim(wav.squeeze(0).cpu().numpy(), top_db=35)
    torchaudio.save(str(wav_path), torch.from_numpy(audio).unsqueeze(0), tts.sr)
    return len(audio) / tts.sr


def listen(wav_path):
    _, whisper = models()
    segments, _ = whisper.transcribe(str(wav_path), language="en", word_timestamps=True)
    return [w for s in segments for w in s.words]


def record_line(line, wav_path):
    """Generate the line until whisper hears it right. Returns (seconds, heard words, match)."""
    best = None
    for seed in SEEDS:
        take = wav_path.with_name(f"{wav_path.stem}-{seed}.wav")
        seconds = say(line["text"], seed, take)
        heard = listen(take)
        score = match(line["text"], " ".join(w.word for w in heard))
        if not best or score > best[2]:
            best = (take, seconds, score, heard)
        if score >= MATCH_OK:
            break
        print(f"  voice: '{line['text']}' heard as '{' '.join(w.word.strip() for w in heard)}' ({score:.0%}), trying again")
    take, seconds, score, heard = best
    if score < MATCH_MINIMUM:
        raise SystemExit(f"The voice kept garbling the line '{line['text']}' ({score:.0%} understood). "
                         "Rephrase it in content/ and run again.")
    take.replace(wav_path)
    for leftover in wav_path.parent.glob(f"{wav_path.stem}-*.wav"):
        leftover.unlink()
    return seconds, heard, score


def ffmpeg(*args):
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", *args], check=True)


def record_voice(lines, folder, min_seconds):
    """Record every line, then lay them out on one voice track long enough for TikTok's 1-minute rule.

    Returns {"wav": path, "total": seconds, "lines": [{text, card, scene, search, start, end, words}]}.
    """
    folder.mkdir(parents=True, exist_ok=True)
    takes = []
    for i, line in enumerate(lines):
        wav = folder / f"line{i:02d}.wav"
        seconds, heard, score = record_line(line, wav)
        takes.append({**line, "file": wav, "seconds": seconds, "heard": heard})
        print(f"  voice {i + 1}/{len(lines)}: {seconds:.1f}s, {score:.0%} understood")

    # fit the 1-minute rule: first longer pauses, then a slightly slower voice (pitch unchanged)
    speech = sum(t["seconds"] for t in takes)
    gaps = sum(t.get("gap", 0.45) for t in takes[:-1])
    target = min_seconds + 1.5
    gap_scale, tempo = 1.0, 1.0
    if speech + gaps < target:
        gap_scale = min(MAX_GAP_SCALE, (target - speech) / gaps) if gaps else 1.0
        if speech + gaps * gap_scale < target:
            tempo = max(MIN_TEMPO, speech / (target - gaps * gap_scale))
    print(f"  voice: {speech:.1f}s of speech, pauses x{gap_scale:.2f}, tempo {tempo:.2f}")

    t, laid = LEAD_IN, []
    for i, take in enumerate(takes):
        # each line at the same loudness, slowed if needed
        norm = take["file"].with_suffix(".norm.wav")
        ffmpeg("-i", str(take["file"]), "-af", f"atempo={tempo},aresample=44100,loudnorm=I=-16:TP=-2:LRA=7",
               "-ar", "44100", "-ac", "1", str(norm))
        seconds = take["seconds"] / tempo
        want = take["text"].split()
        heard = take["heard"]
        words = []
        for k, w in enumerate(want):
            # caption words are the script's words, timed by whisper when it heard as many words
            if len(heard) == len(want):
                s, e = heard[k].start / tempo, heard[k].end / tempo
            else:
                s, e = seconds * k / len(want), seconds * (k + 1) / len(want)
            words.append({"text": w.strip(".,!?;:"), "start": round(t + s, 3), "end": round(t + min(e, seconds), 3)})
        laid.append({key: take[key] for key in ("text", "card", "scene", "search") if key in take}
                    | {"file": norm, "start": round(t, 3), "end": round(t + seconds, 3), "words": words})
        t += seconds + (take.get("gap", 0.45) * gap_scale if i + 1 < len(takes) else 0)
    total = round(max(t + 0.6, min_seconds), 2)

    # one voice track: lines placed on the timeline, light processing, then back to -16 LUFS
    # (the processing used to lower the voice 13 dB under the music: loudnorm must stay last)
    voice = folder / "voice.wav"
    inputs, chains = [], []
    for i, line in enumerate(laid):
        inputs += ["-i", str(line["file"])]
        chains.append(f"[{i}]adelay={round(line['start'] * 1000)}:all=1[a{i}]")
    graph = ";".join(chains) + ";" + "".join(f"[a{i}]" for i in range(len(laid))) + \
        f"amix=inputs={len(laid)}:normalize=0,apad=whole_dur={total},atrim=0:{total}," \
        "equalizer=f=100:t=q:w=1:g=3,equalizer=f=3000:t=q:w=1.5:g=1.5," \
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=150,aecho=1.0:0.9:35:0.06," \
        "loudnorm=I=-16:TP=-1.5:LRA=7"
    ffmpeg(*inputs, "-filter_complex", graph, "-ar", "44100", "-ac", "2", str(voice))
    for line in laid:
        line["file"] = str(line["file"])
    (folder / "voice.json").write_text(json.dumps({"total": total, "lines": laid}, indent=1), encoding="utf-8")
    return {"wav": voice, "total": total, "lines": laid}
