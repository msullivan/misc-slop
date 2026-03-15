import { embedMany, cosineSimilarity } from "ai";
import { readFileSync } from "fs";
import { homedir } from "os";
import { join } from "path";

// Auto-discover AI Gateway API key
if (!process.env.AI_GATEWAY_API_KEY) {
  const sources = [
    () => {
      for (const f of [".env.local", ".env"]) {
        try {
          const m = readFileSync(f, "utf8").match(
            /^AI_GATEWAY_API_KEY=(.+)$/m
          );
          if (m) return m[1].trim();
        } catch {}
      }
    },
    () => {
      try {
        const auth = JSON.parse(
          readFileSync(
            join(homedir(), ".local/share/opencode/auth.json"),
            "utf8"
          )
        );
        return auth?.vercel?.key;
      } catch {}
    },
  ];
  for (const src of sources) {
    const key = src();
    if (key) {
      process.env.AI_GATEWAY_API_KEY = key;
      break;
    }
  }
}

const [a1, a2, b1, b2] = process.argv.slice(2);

if (!a1 || !a2 || !b1 || !b2) {
  console.error("Usage: node embedding-similarity.mjs <a1> <a2> <b1> <b2>");
  process.exit(1);
}

const { embeddings } = await embedMany({
  model: "voyage/voyage-3.5",
  values: [a1, a2, b1, b2],
});

const [emA1, emA2, emB1, emB2] = embeddings;

// Compute difference vectors: a2 - a1 and b2 - b1
const diffA = emA2.map((v, i) => v - emA1[i]);
const diffB = emB2.map((v, i) => v - emB1[i]);

const similarity = cosineSimilarity(diffA, diffB);

console.log(`a1: "${a1}"`);
console.log(`a2: "${a2}"`);
console.log(`b1: "${b1}"`);
console.log(`b2: "${b2}"`);
console.log();
console.log(`similarity(a2 - a1, b2 - b1) = ${similarity.toFixed(4)}`);
