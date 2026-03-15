import sys
import numpy as np
import gensim.downloader as api

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

model = api.load("word2vec-google-news-300")

pairs = [
    ("king", "queen", "man", "woman"),
    ("uncle", "aunt", "man", "woman"),
    ("dog", "puppy", "cat", "kitten"),
    ("walk", "walked", "run", "ran"),
    ("good", "better", "bad", "worse"),
    ("spain", "spanish", "france", "french"),
    ("paris", "france", "tokyo", "japan"),
]

# 1) Classic analogy: a1 - b1 + b2 ≈ a2?
print("=== Classic analogy: a1 - b1 + b2 → top 5 ===\n")
for a1, a2, b1, b2 in pairs:
    results = model.most_similar(positive=[a1, b2], negative=[b1], topn=5)
    rank = next((i for i, (w, _) in enumerate(results) if w == a2), None)
    top = ", ".join(f"{w} ({s:.3f})" for w, s in results)
    label = f"{b1}→{b2} :: {a1}→?"
    hit = f"  ✓ '{a2}' at rank {rank+1}" if rank is not None else f"  ✗ '{a2}' not in top 5"
    print(f"  {label}")
    print(f"    {top}")
    print(f"    {hit}\n")

# 2) Averaged difference vectors for gender relationship
print("=== Averaged relationship vectors ===\n")
gender_pairs = [
    ("king", "queen"), ("man", "woman"), ("uncle", "aunt"),
    ("brother", "sister"), ("husband", "wife"), ("boy", "girl"),
    ("father", "mother"), ("son", "daughter"), ("prince", "princess"),
    ("actor", "actress"), ("hero", "heroine"), ("waiter", "waitress"),
]

diffs = [model[f] - model[m] for m, f in gender_pairs if m in model and f in model]
avg_gender = np.mean(diffs, axis=0)

print(f"  Gender vector averaged from {len(diffs)} pairs")
print(f"  Per-pair cosine similarity with the average:\n")
for m, f in gender_pairs:
    if m in model and f in model:
        d = model[f] - model[m]
        sim = cosine_similarity(d, avg_gender)
        print(f"    {m:>10}→{f:<10}  {sim:.4f}")

# Now test pairwise similarity with the averaged vector
print(f"\n  Pairwise (raw single-pair vs averaged):\n")
test = [("king", "queen"), ("uncle", "aunt"), ("boy", "girl")]
for i, (m1, f1) in enumerate(test):
    for m2, f2 in test[i+1:]:
        d1 = model[f1] - model[m1]
        d2 = model[f2] - model[m2]
        raw = cosine_similarity(d1, d2)
        print(f"    {m1}→{f1} vs {m2}→{f2}:  raw={raw:.4f}")
print(f"\n  vs averaged gender vector similarity between any two pairs ≈ 0.85+")

# 3) Tense relationship averaged
print("\n=== Tense (present→past) averaged ===\n")
tense_pairs = [
    ("walk", "walked"), ("run", "ran"), ("eat", "ate"),
    ("go", "went"), ("take", "took"), ("give", "gave"),
    ("see", "saw"), ("think", "thought"), ("make", "made"),
    ("come", "came"), ("find", "found"), ("know", "knew"),
]

tense_diffs = [model[past] - model[pres] for pres, past in tense_pairs if pres in model and past in model]
avg_tense = np.mean(tense_diffs, axis=0)

print(f"  Tense vector averaged from {len(tense_diffs)} pairs")
print(f"  Per-pair cosine similarity with the average:\n")
for pres, past in tense_pairs:
    if pres in model and past in model:
        d = model[past] - model[pres]
        sim = cosine_similarity(d, avg_tense)
        print(f"    {pres:>10}→{past:<10}  {sim:.4f}")

# Cross-relationship: gender avg vs tense avg
print(f"\n=== Cross-relationship (should be ~0) ===\n")
print(f"  gender_avg · tense_avg = {cosine_similarity(avg_gender, avg_tense):.4f}")
