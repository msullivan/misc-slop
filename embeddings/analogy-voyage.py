"""Nearest-neighbor analogy search using voyage-4-lite embeddings from SQLite."""

import os
import sqlite3
import struct
import sys
import numpy as np

DB_PATH = os.path.join(os.path.dirname(__file__), "embeddings.db")


def load_embeddings(db_path):
    db = sqlite3.connect(db_path)
    rows = db.execute("SELECT word, embedding FROM embeddings ORDER BY rank").fetchall()
    words = []
    vecs = []
    for word, blob in rows:
        vec = struct.unpack(f"{len(blob)//4}f", blob)
        words.append(word)
        vecs.append(vec)
    vecs = np.array(vecs, dtype=np.float32)
    # Pre-compute norms
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1
    normed = vecs / norms
    word_to_idx = {w: i for i, w in enumerate(words)}
    return words, vecs, normed, word_to_idx


def most_similar(query_vec, normed, words, exclude_idxs, topn=5):
    query_norm = query_vec / np.linalg.norm(query_vec)
    sims = normed @ query_norm
    for idx in exclude_idxs:
        sims[idx] = -2
    best = np.argsort(sims)[-topn:][::-1]
    return [(words[i], float(sims[i])) for i in best]


def main():
    if len(sys.argv) < 4:
        print("Usage: python analogy-voyage.py <a1> <a2> <b1> [b2]", file=sys.stderr)
        print("  Finds: a1 → a2 :: b1 → ?", file=sys.stderr)
        print("  If b2 given, checks whether it appears in top results.", file=sys.stderr)
        sys.exit(1)

    a1, a2, b1 = sys.argv[1], sys.argv[2], sys.argv[3]
    b2 = sys.argv[4] if len(sys.argv) > 4 else None

    print(f"Loading embeddings from {DB_PATH}...")
    words, vecs, normed, word_to_idx = load_embeddings(DB_PATH)
    print(f"Loaded {len(words)} words\n")

    check_words = [a1, a2, b1] + ([b2] if b2 else [])
    for w in check_words:
        if w not in word_to_idx:
            print(f"Error: '{w}' not in vocabulary", file=sys.stderr)
            sys.exit(1)

    va1 = vecs[word_to_idx[a1]]
    va2 = vecs[word_to_idx[a2]]
    vb1 = vecs[word_to_idx[b1]]

    # Classic analogy: a1 → a2 :: b1 → ?  (query = b1 - a1 + a2)
    query = vb1 - va1 + va2
    exclude = {word_to_idx[w] for w in [a1, a2, b1]}
    results = most_similar(query, normed, words, exclude, topn=10)

    print(f"  {a1} → {a2} :: {b1} → ?")
    print(f"  Top 10 nearest neighbors:\n")
    for i, (w, s) in enumerate(results):
        marker = " ←" if b2 and w == b2 else ""
        print(f"    {i+1:>2}. {w:<30} {s:.4f}{marker}")

    if b2:
        rank = next((i for i, (w, _) in enumerate(results) if w == b2), None)
        if rank is not None:
            print(f"\n  ✓ '{b2}' found at rank {rank + 1}")
        else:
            print(f"\n  ✗ '{b2}' not in top 10")

        vb2 = vecs[word_to_idx[b2]]
        diff_a = va2 - va1
        diff_b = vb2 - vb1
        cos = np.dot(diff_a, diff_b) / (np.linalg.norm(diff_a) * np.linalg.norm(diff_b))
        print(f"\n  Raw difference vector cosine similarity: {cos:.4f}")


if __name__ == "__main__":
    main()
