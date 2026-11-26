#!/bin/bash
# Logs CPU/GPU temperature, GPU power and fan once a second, synced to disk so the last line survives a hard crash.
out=${1:-out/temps.log}
hw() { for h in /sys/class/hwmon/hwmon*; do [ "$(cat $h/name)" = "$1" ] && echo $h; done; }
g=$(hw amdgpu); c=$(hw k10temp)
while :; do
  echo "$(date +%T) cpu=$(($(cat $c/temp1_input)/1000))C gpu_edge=$(($(cat $g/temp1_input)/1000))C gpu_junction=$(($(cat $g/temp2_input)/1000))C gpu_mem=$(($(cat $g/temp3_input)/1000))C gpu_power=$(($(cat $g/power1_average)/1000000))W fan=$(cat $g/fan1_input)rpm load=$(cut -d' ' -f1 /proc/loadavg)" >> "$out"
  sync "$out"; sleep 1
done
