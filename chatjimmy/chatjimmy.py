#!/usr/bin/env python3
"""
ChatJimmy API client - Send prompts to the hardware-accelerated Llama 3.1 8B model
Usage: chatjimmy.py "Your prompt here" [--system "System prompt"]
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import re


def query_chatjimmy(message, system_prompt="", top_k=8):
    """Query the ChatJimmy API with a message and optional system prompt."""

    url = "https://chatjimmy.ai/api/chat"

    payload = {
        "messages": [
            {"role": "user", "content": message}
        ],
        "chatOptions": {
            "selectedModel": "llama3.1-8B",
            "systemPrompt": system_prompt,
            "topK": top_k
        },
        "attachment": None
    }

    headers = {
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            content = response.read().decode('utf-8')
            return parse_response(content)
    except urllib.error.HTTPError as e:
        print(f"Error: {e.code}")
        print(e.read().decode('utf-8'))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection error: {e}")
        sys.exit(1)


def parse_response(content):
    """Parse the response to extract text and stats."""
    # Extract stats JSON if present
    stats_match = re.search(r'<\|stats\|>(.*?)<\|/stats\|>', content, re.DOTALL)

    if stats_match:
        stats_json = stats_match.group(1)
        text = content[:stats_match.start()].strip()
        try:
            stats = json.loads(stats_json)
        except json.JSONDecodeError:
            stats = None
    else:
        text = content
        stats = None

    return {"text": text, "stats": stats}


def main():
    parser = argparse.ArgumentParser(
        description="Query the ChatJimmy hardware-accelerated Llama 3.1 8B model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  chatjimmy.py "Write a haiku about middle age"
  chatjimmy.py "Explain quantum computing" --system "You are a physics expert"
  chatjimmy.py "Write code" --top-k 12
        """
    )

    parser.add_argument(
        "message",
        help="The prompt to send to the model"
    )

    parser.add_argument(
        "--system",
        default="",
        help="System prompt to set the model's behavior (default: empty)"
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="Top-K parameter for sampling (default: 8)"
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="Display detailed performance stats"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output response as JSON"
    )

    args = parser.parse_args()

    result = query_chatjimmy(args.message, args.system, args.top_k)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["text"])

        if args.stats and result["stats"]:
            print("\n" + "="*50)
            print("STATS:")
            print("="*50)
            stats = result["stats"]
            print(f"Total tokens: {stats.get('total_tokens')}")
            print(f"Prefill tokens: {stats.get('prefill_tokens')} @ {stats.get('prefill_rate'):.0f} tok/s")
            print(f"Decode tokens: {stats.get('decode_tokens')} @ {stats.get('decode_rate'):.0f} tok/s")
            print(f"TTFT: {stats.get('ttft', 0)*1000:.1f}ms")
            print(f"Total duration: {stats.get('total_duration', 0)*1000:.1f}ms")
            print(f"Roundtrip time: {stats.get('roundtrip_time', 0):.0f}ms")


if __name__ == "__main__":
    main()
