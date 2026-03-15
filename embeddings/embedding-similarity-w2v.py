import sys
import numpy as np
import gensim.downloader as api

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

if len(sys.argv) != 5:
    print("Usage: python embedding-similarity-w2v.py <a1> <a2> <b1> <b2>", file=sys.stderr)
    sys.exit(1)

a1, a2, b1, b2 = sys.argv[1:5]

print("Loading word2vec-google-news-300 (first run downloads ~1.7GB)...")
model = api.load("word2vec-google-news-300")

for word in [a1, a2, b1, b2]:
    if word not in model:
        print(f"Error: '{word}' not in vocabulary", file=sys.stderr)
        sys.exit(1)

diff_a = model[a2] - model[a1]
diff_b = model[b2] - model[b1]

similarity = cosine_similarity(diff_a, diff_b)

print(f'a1: "{a1}"')
print(f'a2: "{a2}"')
print(f'b1: "{b1}"')
print(f'b2: "{b2}"')
print()
print(f"similarity(a2 - a1, b2 - b1) = {similarity:.4f}")
