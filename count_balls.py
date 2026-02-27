#!/usr/bin/env python3
"""Parse ligma_model_responses.txt and count mentions of 'balls'"""

import re

with open('ligma_model_responses.txt', 'r') as f:
    content = f.read()

# Split by model entries
western_section = content.split("=== WESTERN MODELS (10) ===")[1].split("=== CHINESE MODELS (10) ===")[0]
chinese_section = content.split("=== CHINESE MODELS (10) ===")[1].split("=== SUMMARY STATISTICS ===")[0]

def count_balls_in_section(section, region_name):
    # Find all model responses with [N/10] pattern
    pattern = r'\[\d+/10\] ([^:]+):\n(.*?)(?=\[\d+/10\]|\Z)'
    matches = re.findall(pattern, section, re.DOTALL)

    print(f"\n{region_name}:")
    print("=" * 60)

    region_count = 0
    responses_mentioning = []

    for model_name, response_text in matches:
        model_name = model_name.strip()

        # Skip error responses
        if "Error:" in response_text:
            continue

        # Count "balls" (case insensitive)
        count = len(re.findall(r'\bballs\b', response_text, re.IGNORECASE))

        if count > 0:
            region_count += count
            responses_mentioning.append((model_name, count))
            print(f"  ✓ {model_name}: {count} mention(s)")

    if not responses_mentioning:
        print("  (none)")

    return region_count, responses_mentioning

western_count, western_models = count_balls_in_section(western_section, "WESTERN MODELS")
chinese_count, chinese_models = count_balls_in_section(chinese_section, "CHINESE MODELS")

print("\n" + "=" * 60)
print("SUMMARY:")
print("=" * 60)
print(f"Western models mentioning 'balls': {len(western_models)}/10")
print(f"Chinese models mentioning 'balls': {len(chinese_models)}/10")
print(f"Total responses mentioning 'balls': {len(western_models) + len(chinese_models)}/18")
print(f"Total mentions of 'balls': {western_count + chinese_count}")
