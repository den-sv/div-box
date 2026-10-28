#!/bin/sh
# Record from the Timebox Mini's microphone. Native format: 8 kHz, mono, 16-bit PCM (Bluetooth headset/HFP),
# so WAV keeps it lossless. Usage: mic/record.sh [seconds] [out.wav]
SECS=${1:-5}; OUT=${2:-"$(dirname "$0")/divoom_$(date +%Y%m%d_%H%M%S).wav"}
IDX=$(ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | sed -n 's/.*\[\([0-9]*\)\] TimeBox.*/\1/p' | head -1)
[ -z "$IDX" ] && { echo "Timebox mic not found (is the box connected?)"; exit 1; }
echo "recording from: $(ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | sed -n "s/.*\[$IDX\] //p" | tail -1) (input $IDX)"
ffmpeg -hide_banner -loglevel error -y -f avfoundation -i ":$IDX" -t "$SECS" -ac 1 -ar 8000 -c:a pcm_s16le "$OUT" && echo "$OUT"
