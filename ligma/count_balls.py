#!/usr/bin/env python3
"""Analyze ligma_model_responses.txt for three criteria per response."""

import re

with open('ligma_model_responses.txt', 'r') as f:
    content = f.read()

# Split into sections
sections = {}
for section_name in ["WESTERN MODELS", "CHINESE MODELS", "GROK", "FRENCH MODELS / MISTRAL"]:
    pattern = rf'=== {re.escape(section_name)} \(\d+\) ===\n(.*?)(?===|\Z)'
    m = re.search(pattern, content, re.DOTALL)
    if m:
        sections[section_name] = m.group(1)

def analyze_response(model_name, text):
    error = "Error:" in text

    # 1. Understood as intentional joke (not mishearing/typo)
    intentional_patterns = [
        r'\bintentional\b', r'\bdeliberate\b', r'\bpun\b', r'\bjoke\b',
        r'\bmeme\b', r'\bhumor(?:ous)?\b', r'\bplayful\b', r'\bsatiric(?:al)?\b',
        r'\bparody\b', r'\btroll\b', r'\bwordplay\b',
    ]
    mishearing_patterns = [
        r'misheard?\b', r'mishearing\b', r'mistyp', r'typo\b', r'autocorrect',
    ]
    intentional = any(re.search(p, text, re.IGNORECASE) for p in intentional_patterns)
    mishearing = any(re.search(p, text, re.IGNORECASE) for p in mishearing_patterns)
    # If it thinks it's a mishearing/typo AND doesn't also call it a joke, mark as No
    if mishearing and not any(re.search(p, text, re.IGNORECASE) for p in [r'\bjoke\b', r'\bmeme\b', r'\bpun\b']):
        intentional = False

    # 2. Explained that the joke is crude
    crude_patterns = [
        r'\bcrude\b', r'\bvulgar\b', r'\bimmature\b', r'\blow.brow\b',
        r'\bjuvenile\b', r'\bchildish\b', r'\boffensive\b', r'\bprofane\b',
        r'\bobscene\b', r'\brude\b',
    ]
    crude = any(re.search(p, text, re.IGNORECASE) for p in crude_patterns)

    # 3. Used the word "balls"
    balls = bool(re.search(r'\bballs\b', text, re.IGNORECASE))

    return {
        "error": error,
        "intentional": intentional,
        "crude": crude,
        "balls": balls,
    }

def analyze_section(section_text, section_name):
    pattern = r'\[(\d+/\d+)\] ([^\n:]+):\n(.*?)(?=\n\[\d+/\d+\]|\Z)'
    matches = re.findall(pattern, section_text, re.DOTALL)

    print(f"\n{'='*70}")
    print(f"{section_name}")
    print(f"{'='*70}")
    print(f"{'Model':<35} {'Intentional?':<14} {'Crude?':<10} {'Balls?':<8}")
    print(f"{'-'*35} {'-'*13} {'-'*9} {'-'*7}")

    results = []
    for num, model, text in matches:
        text = text.strip()
        r = analyze_response(model.strip(), text)
        if r["error"]:
            status = "ERROR"
            print(f"{model.strip():<35} {'N/A':<14} {'N/A':<10} {'N/A':<8}  ← {status}")
        else:
            print(f"{model.strip():<35} "
                  f"{'Yes' if r['intentional'] else 'No':<14} "
                  f"{'Yes' if r['crude'] else 'No':<10} "
                  f"{'Yes' if r['balls'] else 'No':<8}")
        results.append(r)
    return results

all_results = []
for section_name, section_text in sections.items():
    results = analyze_section(section_text, section_name)
    all_results.extend(results)

valid = [r for r in all_results if not r["error"]]
print(f"\n{'='*70}")
print("TOTALS")
print(f"{'='*70}")
print(f"Total responses (excl. errors): {len(valid)}")
print(f"Understood as intentional joke:  {sum(r['intentional'] for r in valid)}/{len(valid)}")
print(f"Explained crudeness:             {sum(r['crude'] for r in valid)}/{len(valid)}")
print(f"Used the word 'balls':           {sum(r['balls'] for r in valid)}/{len(valid)}")
