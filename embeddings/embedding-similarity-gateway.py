"""Embedding similarity via Vercel AI Gateway. No dependencies beyond stdlib."""

import json
import os
import sys
import urllib.request

GATEWAY_URL = "https://ai-gateway.vercel.sh/v3/ai/embedding-model"
MODEL = "voyage/voyage-3.5"


def get_api_key():
    if key := os.environ.get("AI_GATEWAY_API_KEY"):
        return key
    for f in [".env.local", ".env"]:
        try:
            with open(f) as fh:
                for line in fh:
                    if line.startswith("AI_GATEWAY_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except FileNotFoundError:
            pass
    try:
        with open(os.path.expanduser("~/.local/share/opencode/auth.json")) as fh:
            return json.load(fh)["vercel"]["key"]
    except (FileNotFoundError, KeyError):
        pass
    sys.exit("Error: no AI_GATEWAY_API_KEY found")


def embed(values, api_key):
    body = json.dumps({"values": values}).encode()
    req = urllib.request.Request(
        GATEWAY_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "ai-gateway-protocol-version": "0.0.1",
            "ai-auth-method": "api-key",
            "ai-embedding-model-specification-version": "3",
            "ai-model-id": MODEL,
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["embeddings"]


def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b)


if len(sys.argv) != 5:
    print("Usage: python embedding-similarity-gateway.py <a1> <a2> <b1> <b2>", file=sys.stderr)
    sys.exit(1)

a1, a2, b1, b2 = sys.argv[1:5]
api_key = get_api_key()

em_a1, em_a2, em_b1, em_b2 = embed([a1, a2, b1, b2], api_key)

diff_a = [x - y for x, y in zip(em_a2, em_a1)]
diff_b = [x - y for x, y in zip(em_b2, em_b1)]

similarity = cosine_similarity(diff_a, diff_b)

print(f'a1: "{a1}"')
print(f'a2: "{a2}"')
print(f'b1: "{b1}"')
print(f'b2: "{b2}"')
print()
print(f"similarity(a2 - a1, b2 - b1) = {similarity:.4f}")
