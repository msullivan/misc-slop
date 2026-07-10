#!/bin/bash
# Travel to screen coords: ./travel.sh X Y
TX=$1; TY=$2
tmux -L nethack send-keys -t 0 '_'; sleep 1
eval $(tmux -L nethack display -t 0 -p 'CX=#{cursor_x} CY=#{cursor_y}')
MOVES=""
X=$CX; Y=$CY
while [ $X -ne $TX ] || [ $Y -ne $TY ]; do
  DX=0; DY=0
  [ $X -lt $TX ] && DX=1; [ $X -gt $TX ] && DX=-1
  [ $Y -lt $TY ] && DY=1; [ $Y -gt $TY ] && DY=-1
  if [ $DX -eq 1 ] && [ $DY -eq -1 ]; then MOVES="${MOVES}9"
  elif [ $DX -eq 1 ] && [ $DY -eq 1 ]; then MOVES="${MOVES}3"
  elif [ $DX -eq -1 ] && [ $DY -eq -1 ]; then MOVES="${MOVES}7"
  elif [ $DX -eq -1 ] && [ $DY -eq 1 ]; then MOVES="${MOVES}1"
  elif [ $DX -eq 1 ]; then MOVES="${MOVES}6"
  elif [ $DX -eq -1 ]; then MOVES="${MOVES}4"
  elif [ $DY -eq 1 ]; then MOVES="${MOVES}2"
  else MOVES="${MOVES}8"; fi
  X=$((X+DX)); Y=$((Y+DY))
done
[ -n "$MOVES" ] && { tmux -L nethack send-keys -t 0 "$MOVES"; sleep 1; }
eval $(tmux -L nethack display -t 0 -p 'NX=#{cursor_x} NY=#{cursor_y}')
echo "cursor: $CX,$CY -> $NX,$NY (target $TX,$TY)"
tmux -L nethack send-keys -t 0 '.'; sleep 2.5
tmux -L nethack capture-pane -t 0 -p | head -2
