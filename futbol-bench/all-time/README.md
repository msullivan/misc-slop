# futbol-bench-goat: Pelé vs Messi vs Maradona across LLMs and languages

Each model was asked "If you had to pick one, who is the greatest footballer of all time: Pelé, Messi, or Maradona?" in English, Spanish, and Portuguese, with instructions to give an explanation followed by a final answer.

## Results

| Model | English | Spanish | Portuguese |
|---|---|---|---|
| Claude Sonnet 4.6 | Messi | Messi | **Pelé** |
| Claude Opus 4.6 | Messi | Messi | Messi |
| GPT-5.3 | Messi | Messi | Messi |
| GPT-5.1 | Messi | Messi | **Pelé** |
| GPT-4o | **Pelé** | Messi | **Pelé** |
| Gemini 3 Pro | Messi | Messi | **Pelé** |
| Gemini 3.1 Pro | Messi | Messi | **Pelé** |
| Grok 3 | Messi | Messi | Messi |
| Llama 4 Maverick | Messi | Messi | **Pelé** |
| Mistral Large 3 | Messi | Messi | Messi |
| DeepSeek V3.2 | Messi | Messi | Messi |
| Qwen3 Max | Messi | Messi | **Pelé** |
| Kimi K2.5 | Messi | Messi | Messi |
| GLM-5 | Messi | **Refused** | Messi |
| MiniMax M2.7 | Messi | Messi | Messi |

**Final tally: Messi 36, Pelé 8, Maradona 0, Refused 1**

## Highlights

- **Messi won English and Spanish unanimously** (except GPT-4o in English, which picked Pelé).
- **Portuguese went to Pelé** — 7 out of 15 models switched to Pelé when prompted in Portuguese. This is striking: Pelé is Brazilian, Portuguese is the language of Brazil, and the models apparently picked that up. A genuine cultural/linguistic bias surfacing.
- **Maradona got zero votes** across all 45 responses. Despite being many fans' sentimental favorite, no model was willing to put him on top.
- **GLM-5** refused in Spanish ("no es posible declarar un ganador definitivo"), making it the only model to dodge this version.
- **GPT-4o** was the only model to pick Pelé in English — consistent with its general pattern of being more conservative/historical in its framing.
- Unlike the Messi vs Ronaldo bench (43-0), this one actually had some variation. Three-way races are harder for LLMs to duck.

## File structure

```
futbol-bench/all-time/
  en/          # English responses
  es/          # Spanish responses
  pt/          # Portuguese responses
```
