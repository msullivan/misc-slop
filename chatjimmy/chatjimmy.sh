#!/bin/bash
# ChatJimmy API client - Send prompts to the hardware-accelerated Llama 3.1 8B model
# Usage: chatjimmy.sh "Your prompt here" [--system "System prompt"] [--stats]

set -e

# Default values
MESSAGE=""
SYSTEM_PROMPT=""
TOP_K=8
SHOW_STATS=false
JSON_OUTPUT=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --system)
            SYSTEM_PROMPT="$2"
            shift 2
            ;;
        --top-k)
            TOP_K="$2"
            shift 2
            ;;
        --stats)
            SHOW_STATS=true
            shift
            ;;
        --json)
            JSON_OUTPUT=true
            shift
            ;;
        --help|-h)
            cat << 'EOF'
ChatJimmy API client - Query the hardware-accelerated Llama 3.1 8B model

Usage: chatjimmy.sh "Your prompt" [OPTIONS]

Options:
  --system PROMPT    Set system prompt to customize model behavior
  --top-k N          Top-K parameter for sampling (default: 8)
  --stats            Display detailed performance stats
  --json             Output response as JSON
  --help             Show this help message

Examples:
  chatjimmy.sh "Write a haiku about middle age"
  chatjimmy.sh "Explain quantum computing" --system "You are a physics expert"
  chatjimmy.sh "Write code" --top-k 12 --stats
EOF
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            if [ -z "$MESSAGE" ]; then
                MESSAGE="$1"
            fi
            shift
            ;;
    esac
done

if [ -z "$MESSAGE" ]; then
    echo "Error: Message is required" >&2
    echo "Usage: chatjimmy.sh \"Your prompt here\" [--system \"System prompt\"] [--stats]" >&2
    exit 1
fi

# Escape special characters for JSON
escape_json() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    echo "$s"
}

MESSAGE_ESCAPED=$(escape_json "$MESSAGE")
SYSTEM_ESCAPED=$(escape_json "$SYSTEM_PROMPT")

# Build JSON payload
read -r -d '' PAYLOAD << EOF || true
{
  "messages": [
    {"role":"user","content":"$MESSAGE_ESCAPED"}
  ],
  "chatOptions": {
    "selectedModel":"llama3.1-8B",
    "systemPrompt":"$SYSTEM_ESCAPED",
    "topK":$TOP_K
  },
  "attachment":null
}
EOF

# Make the request
RESPONSE=$(curl -s -X POST https://chatjimmy.ai/api/chat \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

# Extract text and stats
if [[ $RESPONSE =~ \<\|stats\|\>(.*)\<\|\/stats\|\> ]]; then
    STATS="${BASH_REMATCH[1]}"
    TEXT="${RESPONSE%<|stats|>*}"
else
    TEXT="$RESPONSE"
    STATS=""
fi

# Output
if [ "$JSON_OUTPUT" = true ]; then
    if [ -n "$STATS" ]; then
        echo "{\"text\":\"$(escape_json "$TEXT")\",\"stats\":$STATS}"
    else
        echo "{\"text\":\"$(escape_json "$TEXT")\"}"
    fi
else
    echo "$TEXT"

    if [ "$SHOW_STATS" = true ] && [ -n "$STATS" ]; then
        echo ""
        echo "=================================================="
        echo "STATS:"
        echo "=================================================="

        # Parse and display stats
        TOTAL_TOKENS=$(echo "$STATS" | grep -o '"total_tokens":[0-9]*' | cut -d: -f2)
        PREFILL_TOKENS=$(echo "$STATS" | grep -o '"prefill_tokens":[0-9]*' | cut -d: -f2)
        PREFILL_RATE=$(echo "$STATS" | grep -o '"prefill_rate":[0-9.]*' | cut -d: -f2)
        DECODE_TOKENS=$(echo "$STATS" | grep -o '"decode_tokens":[0-9]*' | cut -d: -f2)
        DECODE_RATE=$(echo "$STATS" | grep -o '"decode_rate":[0-9.]*' | cut -d: -f2)
        TTFT=$(echo "$STATS" | grep -o '"ttft":[0-9.]*' | cut -d: -f2)
        TOTAL_DURATION=$(echo "$STATS" | grep -o '"total_duration":[0-9.]*' | cut -d: -f2)
        ROUNDTRIP=$(echo "$STATS" | grep -o '"roundtrip_time":[0-9.]*' | cut -d: -f2)

        [ -n "$TOTAL_TOKENS" ] && echo "Total tokens: $TOTAL_TOKENS"
        [ -n "$PREFILL_TOKENS" ] && printf "Prefill tokens: %s @ %.0f tok/s\n" "$PREFILL_TOKENS" "$PREFILL_RATE"
        [ -n "$DECODE_TOKENS" ] && printf "Decode tokens: %s @ %.0f tok/s\n" "$DECODE_TOKENS" "$DECODE_RATE"
        [ -n "$TTFT" ] && printf "TTFT: %.1fms\n" "$(echo "$TTFT * 1000" | bc)"
        [ -n "$TOTAL_DURATION" ] && printf "Total duration: %.1fms\n" "$(echo "$TOTAL_DURATION * 1000" | bc)"
        [ -n "$ROUNDTRIP" ] && printf "Roundtrip time: %.0fms\n" "$ROUNDTRIP"
    fi
fi
