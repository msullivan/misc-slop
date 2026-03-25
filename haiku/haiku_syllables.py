import argparse
import re

import cmudict


HAIKUS = {
    "openai/gpt-5.2": "Reading glasses fog, / Laugh lines deepen, knees protest-- / Still, the heart leans forward.",
    "openai/gpt-5.1-instant": "Lines blur in the dusk, / Middle age hums soft and low-- / Warm light holds the years.",
    "openai/gpt-4o": "Fading daylight's glow, / Quiet wisdom's gentle sway, / Leaves fall, rich and slow.",
    "openai/gpt-4.1": "Silver in the hair, / Stories linger in the heart-- / Dawn and dusk embrace.",
    "openai/gpt-4o-mini": "Time's gentle embrace, / Wisdom blooms in quiet hearts, / Dreams shift like the tide.",
    "openai/o3": "Morning light still warm-- / half-traveled road behind me, / horizon ahead.",
    "openai/gpt-oss-20b": "Leaves fall mid-winter, / Years etched amber twilight, / Still breath hums forward.",
    "anthropic/claude-3-haiku": "Midlife's crossroads met, / Wisdom and weariness blend, / Searching for purpose.",
    "anthropic/claude-3.5-sonnet": "Gray hairs multiply / Reading glasses on the shelf / Kids grow tall as me",
    "anthropic/claude-3.7-sonnet": "Gray hairs emerging / Wisdom grows as time passes / Youth's echo lingers",
    "anthropic/claude-opus-4.1": "Reading glasses perched, / knees creak on morning stairs--yet / dreams still take no naps.",
    "anthropic/claude-sonnet-4": "Gray threads appear now-- / children grow while parents age, / wisdom slowly blooms.",
    "anthropic/claude-haiku-4.5": "Gray threads blend with brown, / halfway through the mountain climb-- / the view gets better.",
    "google/gemini-2.5-pro": "More past than future, / You stand on the central hill, / And see both ways now.",
    "google/gemini-2.5-flash": "Grey hairs softly show, / Between the young and old, / Life's new chapter starts.",
    "google/gemini-2.0-flash": "The mirror reflects, / Lines deepen, wisdom arrives, / A new chapter blooms.",
    "google/gemini-3-pro-preview": "Silver threads appear, / Wisdom grows as time moves on, / Life's sweet afternoon.",
    "google/gemini-3-flash": "Halfway up the hill, / Pausing for a deeper breath, / The view starts to clear.",
    "deepseek/deepseek-r1": "Leaves once green now gold-- / Mirror whispers of fleeting time, / River seeks the sea.",
    "deepseek/deepseek-v3": "Gray strands in the glass, / time's weight softens sharp edges-- / warm sun, deeper roots.",
    "deepseek/deepseek-v3.2": "Salt and pepper hair, / A calendar of half-done lists-- / Deep roots, slower winds.",
    "deepseek/deepseek-v3.2-thinking": "At the temple, a strand / of silver appears overnight -- / autumn in the pines.",
    "alibaba/qwen-3-14b": "Midlife's quiet dawn, / Balancing yesterday's storms / Roots deepen, still growing.",
    "alibaba/qwen-3-32b": "Crossroads of youth and years, / Body hums with quiet strength-- / Now blooms the present.",
    "alibaba/qwen3-max": "Silver threads appear-- / Midlife's quiet weight settles, / Still dreams hum softly.",
    "alibaba/qwen3.5-plus": "Gray hairs start to show, / Knees creak when the rain rolls in, / Wisdom fills the cup.",
    "alibaba/qwen3-coder": "Wisdom lines deepen / Children grow tall, parents fade / Seasons shift quietly",
    "alibaba/qwen3-next-80b-a3b-instruct": "Gray hairs catch the light, / still chasing dreams through quiet days-- / tea cools, the clock ticks.",
    "xai/grok-3": "Middle age arrives, / Wisdom blooms in quiet strength, / Years paint silver streaks.",
    "xai/grok-3-mini": "Midlife's quiet path, / Memories bloom like autumn leaves, / Shadows lengthen now.",
    "xai/grok-4": "Gray hairs whisper truths, / Memories weave through the years, / Wisdom's quiet dawn.",
    "mistral/mistral-large-3": "Midlife's quiet dawn-- / laugh lines map the years ahead, / roots hold the old tree.",
    "mistral/mistral-medium": "Gray strands in the breeze-- / the mirror holds a stranger, / still laughing at time.",
    "mistral/mistral-small": "Middle age arrives-- / silver threads in morning light, / wisdom weighs the years.",
    "meta/llama-3.3-70b": "Silver threads appear / Wisdom lines upon my face / Life's gentle descent",
    "meta/llama-4-maverick": "Lines on weathered face / Midlife's gentle, quiet storm / Wisdom's subtle grasp",
    "moonshotai/kimi-k2": "Mirror shows more lines, / knees creak louder than dawn birds-- / time sips me slowly.",
}

VOWELS = "aeiouy"
CMU = cmudict.dict()


def syllables_heuristic(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    specials = {
        "hour": 1,
        "our": 1,
        "one": 1,
        "once": 1,
        "two": 1,
        "eye": 1,
        "you": 1,
        "queue": 1,
        "quiet": 2,
        "fire": 1,
        "every": 2,
        "family": 3,
        "business": 2,
        "mirror": 2,
        "flowers": 2,
        "silver": 2,
        "higher": 2,
        "cough": 1,
        "laugh": 1,
    }
    if word in specials:
        return specials[word]
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ye")) and count > 1:
        count -= 1
    if word.endswith("le") and len(word) > 2 and word[-3] not in VOWELS:
        count += 1
    if word.endswith("ed") and len(word) > 2 and word[-3] not in VOWELS:
        count -= 1
    if word.endswith("es") and len(word) > 2 and word[-3] not in VOWELS:
        count -= 1
    return max(count, 1)


def count_cmu(word: str) -> int | None:
    if word in CMU:
        pron = CMU[word][0]
        return sum(1 for p in pron if p[-1].isdigit())
    return None


def syllables_in_word(word: str) -> int:
    w = re.sub(r"[^a-z']", "", word.lower()).replace("'", "")
    if not w:
        return 0
    cmu_count = count_cmu(w)
    if cmu_count is not None:
        return cmu_count
    n = syllables_heuristic(w)
    print("!!", w, n)
    # assert False, (w, n)
    return n


def syllables_in_line(line: str) -> int:
    words = re.findall(r"[A-Za-z'\-]+", line)
    return sum(syllables_in_word(w) for w in words)


def split_lines(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\s*/\s*", text) if p.strip()]
    if len(parts) == 1:
        parts = [p.strip() for p in text.splitlines() if p.strip()]
    return parts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-good", action="store_true")
    args = parser.parse_args()

    results = {}
    for model, poem in HAIKUS.items():
        lines = split_lines(poem)
        counts = [syllables_in_line(line) for line in lines]
        results[model] = {"lines": lines, "counts": counts}

    bad = {}
    good = {}
    for model, info in results.items():
        counts = info["counts"]
        if len(counts) != 3 or counts != [5, 7, 5]:
            bad[model] = counts
        else:
            good[model] = counts

    print(f"total {len(HAIKUS)}")
    print(f"bad {len(bad)}")
    print("bad_models")
    for model in sorted(bad):
        print(f"{model} {bad[model]}")

    if args.show_good:
        print("good_models")
        for model in sorted(good):
            print(f"{model} {good[model]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
