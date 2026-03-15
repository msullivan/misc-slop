"""Collect voyage-4-lite embeddings for top 100k word2vec words via Vercel AI Gateway."""

import json
import os
import sqlite3
import struct
import sys
import time
import urllib.request
import urllib.error

GATEWAY_URL = "https://ai-gateway.vercel.sh/v3/ai/embedding-model"
MODEL = "voyage/voyage-4-lite"
BATCH_SIZE = 500
TOTAL_WORDS = 100_000


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


def embed_batch(values, api_key):
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["embeddings"]


def pack_embedding(embedding):
    return struct.pack(f"{len(embedding)}f", *embedding)


def get_words():
    """Get top 100k words from word2vec vocab (sorted by frequency)."""
    import gensim.downloader as api
    print("Loading word2vec vocabulary...")
    model = api.load("word2vec-google-news-300")
    words = model.index_to_key[:TOTAL_WORDS]
    print(f"Got {len(words)} words")
    return words


def init_db(db_path):
    db = sqlite3.connect(db_path)
    db.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            rank INTEGER PRIMARY KEY,
            word TEXT NOT NULL,
            embedding BLOB NOT NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_word ON embeddings(word)")
    db.commit()
    return db


def main():
    db_path = "embeddings.db"
    api_key = get_api_key()
    words = get_words()

    db = init_db(db_path)

    # Check how far we got (for resume)
    done = db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    if done > 0:
        print(f"Resuming: {done}/{TOTAL_WORDS} already done")

    start_idx = done
    total_batches = (TOTAL_WORDS - start_idx + BATCH_SIZE - 1) // BATCH_SIZE
    t0 = time.time()

    for batch_num, i in enumerate(range(start_idx, TOTAL_WORDS, BATCH_SIZE)):
        batch_words = words[i : i + BATCH_SIZE]

        for attempt in range(5):
            try:
                embeddings = embed_batch(batch_words, api_key)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    wait = 2 ** attempt
                    print(f"  HTTP {e.code}, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        else:
            sys.exit(f"Failed after 5 retries at batch starting at index {i}")

        rows = [
            (i + j, word, pack_embedding(emb))
            for j, (word, emb) in enumerate(zip(batch_words, embeddings))
        ]
        db.executemany("INSERT INTO embeddings (rank, word, embedding) VALUES (?, ?, ?)", rows)
        db.commit()

        elapsed = time.time() - t0
        done_now = i + len(batch_words) - start_idx
        rate = done_now / elapsed if elapsed > 0 else 0
        eta = (TOTAL_WORDS - start_idx - done_now) / rate if rate > 0 else 0
        print(
            f"  [{i + len(batch_words):>6}/{TOTAL_WORDS}]"
            f"  batch {batch_num + 1}/{total_batches}"
            f"  {rate:.0f} words/s"
            f"  ETA {eta:.0f}s"
        )

    total = time.time() - t0
    print(f"\nDone! {TOTAL_WORDS} embeddings in {total:.1f}s -> {db_path}")


if __name__ == "__main__":
    main()
