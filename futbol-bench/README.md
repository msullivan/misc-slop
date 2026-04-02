# futbol-bench: Messi vs Ronaldo across LLMs and languages

Each model was asked "If you had to pick, is Messi or Ronaldo better?" in English, Spanish, and Portuguese, with instructions to give an explanation followed by a final answer.

## Results

| Model | English | Spanish | Portuguese |
|---|---|---|---|
| Claude Sonnet 4.6 | Messi | Messi | Messi |
| Claude Opus 4.6 | Messi | Messi | Messi |
| GPT-5.3 | Messi | Messi | Messi |
| GPT-5.1 | Messi | Messi | Messi |
| GPT-4o | Messi | Messi | Messi |
| Gemini 3 Pro | **Refused** | **Refused** | Messi |
| Gemini 3.1 Pro | Messi | Messi | Messi |
| Grok 3 | Messi | Messi | Messi |
| Llama 4 Maverick | Messi | Messi | Messi |
| Mistral Large 3 | Messi | Messi | Messi |
| DeepSeek V3.2 | Messi | Messi | Messi |
| Qwen3 Max | Messi | Messi | Messi |
| Kimi K2.5 | Messi | Messi | Messi |
| GLM-5 | Messi | Messi | Messi |
| MiniMax M2.7 | Messi | Messi | Messi |

**Final tally: Messi 43, Ronaldo 0, Refused 2**

## Highlights

- **Unanimous Messi** — across 15 models and 3 languages, not a single model picked Ronaldo. Zero. Nada. Nenhum.
- **Gemini 3 Pro** refused to answer in English ("As an AI, I am not supposed to express opinions on sensitive public interest topics") and Spanish ("No hay una respuesta única"), but then picked Messi in Portuguese. Apparently the GOAT debate is only a sensitive topic in some languages.
- **Claude Sonnet 4.6** was the only model to include the GOAT emoji in its Spanish and Portuguese answers.
- Every model that did answer gave largely the same reasoning: Messi's playmaking + World Cup 2022 + 8 Ballon d'Ors edges out Ronaldo's athleticism and multi-league success.
- The Chinese models (Qwen3, Kimi, GLM-5, DeepSeek, MiniMax) all picked Messi too — no regional variation whatsoever.

## File structure

```
futbol-bench/
  en/          # English responses
  es/          # Spanish responses
  pt/          # Portuguese responses
```
