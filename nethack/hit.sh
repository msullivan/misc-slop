#!/bin/bash
# One attack in direction $1, clear one More, then report: message, HP, and 7x7 map around @
D=$1
tmux -L nethack send-keys -t 0 F "$D"; sleep 0.5
tmux -L nethack send-keys -t 0 Enter; sleep 0.4
S=$(tmux -L nethack capture-pane -t 0 -p)
eval $(tmux -L nethack display -t 0 -p 'CX=#{cursor_x} CY=#{cursor_y}')
echo "MSG: $(echo "$S" | sed -n 1p | tr -s ' ')"
echo "STATUS: $(echo "$S" | grep -oE 'HP:[0-9]+\([0-9]+\)|T:[0-9]+|Dlvl:[0-9]+' | tr '\n' ' ')"
echo "ME: $CX,$CY  MAP:"
echo "$S" | awk -v cy=$CY -v cx=$CX 'NR-1>=cy-3 && NR-1<=cy+3 {print "  " substr($0, cx-5>0?cx-5:1, 13)}'
