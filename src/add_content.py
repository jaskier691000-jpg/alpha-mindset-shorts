"""Merge written monologues from content/*.json into topics.json, in the order of topic_plan.json, and check them.

Each content file is a list of topics:
  {"id": "am0001",
   "lines": [{"text": "Nobody is coming to save you.", "card": "NOBODY IS COMING", "scene": "rain-alone",
              "search": "man rain night city", "gap": 0.6}, ...],
   "caption": "One searchable sentence about the video.",
   "hashtags": "#discipline #selfimprovement #mindset #motivation"}
- text: what the deep voice says (one short sentence or two), written for the voice: no digits, no symbols.
- card: optional big punch word(s) shown at the top (≤ 3 words). The hook line always has one.
- scene: the AI cinema library category for this line (assets/library/library.json → categories).
- search: 2-5 words to find real Pixabay footage for this line (the hook line may skip it).
- gap: optional pause after the line, in seconds (default 0.45; 0.6-0.8 after a strong line).

Run: python src/add_content.py   (plain Python, no packages needed: the Monday cloud routine runs it too)
"""
import json
import re
import sys

from common import ROOT, load_json, save_json

WORDS_PER_SECOND = 3.5      # Chatterbox Nano with the deep reference voice (measured 31 Oct 2026: 154 words = 43.5 s)
LINES = (14, 22)
WORDS = (175, 215)          # 154 words still needed the maximum stretch to pass 61 s; 215 stays under ~75 s
CARDS = (5, 10)
BANNED = ("females", "kill yourself", "kys")  # dehumanising or harmful wording never goes out
VOICE_UNSAFE = re.compile(r"[0-9%&$#@\"()\[\]{}*_/\\<>|~^=+]")


def categories():
    lib = load_json(ROOT / "assets" / "library" / "library.json", {})
    return {c["cat"] for c in lib.get("categories", [])}


def check_topic(item, cats):
    """Return the list of problems of one written topic (empty when it is fine)."""
    tid, problems = item.get("id", "?"), []
    lines = item.get("lines", [])
    if not LINES[0] <= len(lines) <= LINES[1]:
        problems.append(f"{tid}: {len(lines)} lines (need {LINES[0]}-{LINES[1]})")
    words = sum(len(l.get("text", "").split()) for l in lines)
    if not WORDS[0] <= words <= WORDS[1]:
        problems.append(f"{tid}: {words} spoken words (need {WORDS[0]}-{WORDS[1]})")
    cards = [l["card"] for l in lines if l.get("card")]
    if not CARDS[0] <= len(cards) <= CARDS[1]:
        problems.append(f"{tid}: {len(cards)} punch cards (need {CARDS[0]}-{CARDS[1]})")
    for n, line in enumerate(lines, 1):
        text = line.get("text", "")
        where = f"{tid} line {n}"
        if not text or not 2 <= len(text.split()) <= 20:
            problems.append(f"{where}: {len(text.split())} words (2-20)")
        if VOICE_UNSAFE.search(text):
            problems.append(f"{where}: digits or symbols the voice can't read: '{text}'")
        if text and text[-1] not in ".!?":
            problems.append(f"{where}: must end with . ! or ?")
        if any(b in text.lower() for b in BANNED):
            problems.append(f"{where}: wording not allowed on the channel: '{text}'")
        card = line.get("card")
        if card and (len(card.split()) > 3 or len(card) > 16 or not re.fullmatch(r"[A-Z' ]+", card)):
            problems.append(f"{where}: card '{card}' must be 1-3 UPPERCASE words, 16 letters max")
        if cats and line.get("scene") not in cats:
            problems.append(f"{where}: scene '{line.get('scene')}' is not a library category")
        search = line.get("search", "")
        if n > 1 and not search:
            problems.append(f"{where}: missing 'search' words for real footage")
        if search and (not 2 <= len(search.split()) <= 5 or re.search(r"[^a-z ]", search)):
            problems.append(f"{where}: search '{search}' must be 2-5 lowercase words")
        gap = line.get("gap", 0.45)
        if not isinstance(gap, (int, float)) or not 0.2 <= gap <= 1.2:
            problems.append(f"{where}: gap {gap} must be between 0.2 and 1.2 seconds")
    if lines:
        if len(lines[0].get("text", "").split()) > 10:
            problems.append(f"{tid}: the hook (line 1) must be 10 words or fewer")
        if not lines[0].get("card"):
            problems.append(f"{tid}: the hook (line 1) needs a card, it is the first thing viewers see")
        if "follow" not in lines[-1].get("text", "").lower():
            problems.append(f"{tid}: the last line must ask to follow")
        repeats = [n for n in range(1, len(lines)) if lines[n].get("scene") == lines[n - 1].get("scene")]
        if repeats:
            problems.append(f"{tid}: same scene on lines {', '.join(f'{n} and {n + 1}' for n in repeats)}")
    tags = item.get("hashtags", "").split()
    if len(tags) != 4 or any(not re.fullmatch(r"#[a-z0-9]+", t) for t in tags) or "#alphamindset" in tags:
        problems.append(f"{tid}: hashtags must be 4 lowercase tags (the account adds #alphamindset): '{item.get('hashtags')}'")
    caption = item.get("caption", "")
    if not 8 <= len(caption.split()) <= 30 or "#" in caption:
        problems.append(f"{tid}: caption must be one sentence of 8-30 words, without hashtags")
    return problems


def spoken_seconds(item):
    lines = item["lines"]
    words = sum(len(l["text"].split()) for l in lines)
    return words / WORDS_PER_SECOND + sum(l.get("gap", 0.45) for l in lines[:-1])


def main():
    lang = "en"
    plan = load_json(ROOT / "topic_plan.json")
    plan_ids = {p["id"]: p for p in plan}
    cats = categories()
    if not cats:
        print("Note: assets/library/library.json not found, scene names not checked.")

    written, problems = {}, []
    for path in sorted((ROOT / "content").glob("*.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            if item.get("id") not in plan_ids:
                problems.append(f"{path.name}: '{item.get('id')}' is not in topic_plan.json")
                continue
            if item["id"] in written:
                problems.append(f"{item['id']}: written twice")
            problems += check_topic(item, cats)
            written[item["id"]] = item
    # every monologue is new: no hook used twice, no sentence of 6+ words repeated (the routine once reused an example)
    seen = {}
    for tid, item in written.items():
        for n, line in enumerate(item.get("lines", []), 1):
            text = line.get("text", "").lower().strip()
            if n == 1 or len(text.split()) >= 6:
                if text in seen:
                    problems.append(f"{tid} line {n}: already used in {seen[text]}: '{line['text']}'")
                else:
                    seen[text] = f"{tid} line {n}"
    if problems:
        sys.exit("Problems to fix:\n" + "\n".join(problems))

    topics, short = [], []
    for p in plan:
        item = written.get(p["id"])
        if not item:
            continue
        topics.append({"id": p["id"], "category": p["category"], "title": {lang: p["title"]},
                       "lines": {lang: item["lines"]}, "caption": {lang: item["caption"]},
                       "hashtags": {lang: item["hashtags"]}})
        if spoken_seconds(item) < 55:
            short.append(f"  {p['id']}: about {spoken_seconds(item):.0f}s of voice before stretching (aim for 55+)")
    save_json(ROOT / "topics.json", topics)
    print(f"topics.json: {len(topics)} topics written out of {len(plan)} planned.")
    if short:
        print("Short monologues (the voice will be slowed a little, add a line if you can):\n" + "\n".join(short))


if __name__ == "__main__":
    main()
