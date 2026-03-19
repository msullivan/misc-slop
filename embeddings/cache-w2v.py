"""Cache top 100k word2vec vectors as fast-loading numpy files."""

import os
import numpy as np
import gensim.downloader as api

N = 100_000
DIR = os.path.dirname(__file__)

print("Loading full word2vec model (slow, one-time)...")
model = api.load("word2vec-google-news-300")

words = model.index_to_key[:N]
vecs = np.array([model[w] for w in words], dtype=np.float32)

np.save(os.path.join(DIR, "w2v-vecs.npy"), vecs)
np.save(os.path.join(DIR, "w2v-words.npy"), np.array(words))
print(f"Saved {N} vectors to w2v-vecs.npy + w2v-words.npy ({vecs.nbytes / 1e6:.0f}MB)")
