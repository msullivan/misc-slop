"""Abuse Jev as a character-level language model.

Jev doesn't generate text; it answers multiple-choice questions. So we ask it
"what is the next character of this haiku?" with every character as a choice,
one gateway round trip per character. Please do not do this.

    uv run haiku.py [topic] [--temperature T] [--words]

Character mode produces garbage ("aaaaaaa"): Jev has basically no spelling
signal. ``--words`` picks from a fixed vocabulary instead, which sort of works.
"""

import argparse
import asyncio
import random
import string
import time

import ai

JEV = "typesafe-ai/jev"
MAX_TOKENS = 120

# Choice key -> the text it emits.
TOKENS = {c: c for c in string.ascii_lowercase}
TOKENS |= {"space": " ", "newline": "\n", "comma": ",", "apostrophe": "'"}
TOKENS |= {"end": ""}

CRITERIA: dict[str, str | None] = {c: None for c in string.ascii_lowercase}
CRITERIA |= {
    "space": "A space: the current word is finished",
    "newline": "A line break: the current line is finished",
    "comma": "A comma",
    "apostrophe": "An apostrophe",
    "end": "Nothing: the haiku is already complete (three lines, 5-7-5)",
}

VOCAB = """
the a of in on and to my your no one all is was will not now still last first
cold dark pale quiet silent empty old white black grey soft slow deep long
final death life grave breath bones dust ash earth stone snow frost winter
autumn leaves leaf petals blossom moon sun night dawn dusk shadow light wind
rain river sea sky crow candle door bell name heart hands eyes voice silence
sleep dream memory time end falls fall fades fade waits wait returns return
takes comes goes rests remains whispers forgets remembers beneath beyond after
before into without again away only even we i you it
""".split()

WORD_CRITERIA: dict[str, str | None] = {w: None for w in VOCAB}
WORD_CRITERIA |= {
    "NEWLINE": "End the current line",
    "END": "Nothing: the haiku is already complete (three lines, 5-7-5)",
}


def sample(probs: dict[str, float], temperature: float) -> str:
    if temperature <= 0:
        return max(probs, key=probs.__getitem__)
    keys = list(probs)
    weights = [probs[k] ** (1 / temperature) for k in keys]
    return random.choices(keys, weights)[0]


async def next_token(
    model: ai.Model, topic: str, text: str, temp: float, words: bool
) -> str:
    unit = "word" if words else "character"
    result = await ai.ops.experimental_evaluate(
        model,
        {"task": f"Writing a haiku about {topic}", "haiku_so_far": text},
        {
            "next": ai.ops.ChoiceQuestion(
                instructions=(
                    f"What is the next {unit} of this haiku about {topic}? "
                    "It should spell real English words and end after three "
                    "lines of 5, 7, and 5 syllables."
                ),
                criteria=WORD_CRITERIA if words else CRITERIA,
            )
        },
    )
    answer = result.value["next"]
    assert isinstance(answer, ai.ops.ChoiceAnswer)
    if answer.probabilities:
        return sample(answer.probabilities, temp)
    return answer.choice


async def run(topic: str, temp: float, words: bool) -> None:
    model = ai.get_model(JEV)
    if not model.provider.is_configured():
        print("Set AI_GATEWAY_API_KEY to run this example.")
        return

    text = ""
    start = time.perf_counter()
    for calls in range(1, MAX_TOKENS + 1):
        key = await next_token(model, topic, text, temp, words)
        if key in ("end", "END") and (not words or key == "END"):
            break
        if not words:
            piece = TOKENS[key]
        elif key == "NEWLINE":
            piece = "\n"
        else:
            piece = key if text.endswith("\n") or not text else " " + key
        text += piece
        print(piece, end="", flush=True)

    elapsed = time.perf_counter() - start
    print(f"\n\n[{calls} requests, {elapsed:.1f}s, {len(text) / elapsed:.1f} chars/s]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", nargs="?", default="death")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--words", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.topic, args.temperature, args.words))


if __name__ == "__main__":
    main()
