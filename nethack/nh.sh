#!/bin/bash
# Send keys to the nethack tmux session, then capture the screen.
# Usage: ./nh.sh [-s SLEEP] [keys...]   (each arg passed to send-keys separately)
#        ./nh.sh                        (just capture)
SLEEP=1
if [ "$1" = "-s" ]; then SLEEP="$2"; shift 2; fi
if [ $# -gt 0 ]; then
  tmux -L nethack send-keys -t 0 "$@"
  sleep "$SLEEP"
fi
tmux -L nethack capture-pane -t 0 -p
