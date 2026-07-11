#!/bin/bash
# Step in direction(s) $@, then print T/HP and 9x5 neighborhood around @
for D in "$@"; do
  tmux -L nethack send-keys -t 0 "$D"
  sleep 0.6
done
S=$(tmux -L nethack capture-pane -t 0 -p)
eval $(tmux -L nethack display -t 0 -p 'CX=#{cursor_x} CY=#{cursor_y}')
echo "MSG: $(echo "$S" | sed -n 1p | tr -s ' ')"
echo "STATUS: $(echo "$S" | grep -oE 'HP:[0-9]+\([0-9]+\)|T:[0-9]+' | tr '\n' ' ') @($CX,$CY)"
echo "$S" | awk -v cy=$CY -v cx=$CX 'NR-1>=cy-2 && NR-1<=cy+2 {print "  ["substr($0, cx-3, 9)"]"}'
