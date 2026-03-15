"""Nearest-neighbor analogy search using voyage-4-lite embeddings from SQLite."""

import sqlite3
import struct
import sys
import numpy as np

DB_PATH = "embeddings.db"


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
    if len(sys.argv) < 5:
        print("Usage: python analogy-voyage.py <a1> <a2> <b1> <b2>", file=sys.stderr)
        print("  Finds: b1 → b2 :: a1 → ?  (i.e. a1 - b1 + b2)", file=sys.stderr)
        print("  Also shows raw difference vector similarity.", file=sys.stderr)
        sys.exit(1)

    a1, a2, b1, b2 = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

    print(f"Loading embeddings from {DB_PATH}...")
    words, vecs, normed, word_to_idx = load_embeddings(DB_PATH)
    print(f"Loaded {len(words)} words\n")

    for w in [a1, a2, b1, b2]:
        if w not in word_to_idx:
            print(f"Error: '{w}' not in vocabulary", file=sys.stderr)
            sys.exit(1)

    va1 = vecs[word_to_idx[a1]]
    va2 = vecs[word_to_idx[a2]]
    vb1 = vecs[word_to_idx[b1]]
    vb2 = vecs[word_to_idx[b2]]

    # Classic analogy: a1 - b1 + b2 ≈ a2?
    query = va1 - vb1 + vb2
    exclude = {word_to_idx[w] for w in [a1, b1, b2]}
    results = most_similar(query, normed, words, exclude, topn=10)

    rank = next((i for i, (w, _) in enumerate(results) if w == a2), None)

    print(f"  {b1} → {b2} :: {a1} → ?")
    print(f"  Top 10 nearest neighbors:\n")
    for i, (w, s) in enumerate(results):
        marker = " ←" if w == a2 else ""
        print(f"    {i+1:>2}. {w:<30} {s:.4f}{marker}")

    if rank is not None:
        print(f"\n  ✓ '{a2}' found at rank {rank + 1}")
    else:
        print(f"\n  ✗ '{a2}' not in top 10")

    # Also show raw difference vector similarity for comparison
    diff_a = va2 - va1
    diff_b = vb2 - vb1
    cos = np.dot(diff_a, diff_b) / (np.linalg.norm(diff_a) * np.linalg.norm(diff_b))
    print(f"\n  Raw difference vector cosine similarity: {cos:.4f}")


if __name__ == "__main__":
    main()
