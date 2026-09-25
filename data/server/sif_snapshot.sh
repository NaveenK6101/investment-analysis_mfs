#!/bin/bash
# Daily snapshot of AMFI's SIF NAV file. AMFI only serves "today's" file (no history),
# so this keeps each day's copy; the laptop-side build_sif_dataset.py ingests them by the
# NAV date inside the file, so a missed pull/day never corrupts anything.
#
# Install on the server (server clock is IST; AMFI updates the file around 08:45 IST):
#   mkdir -p ~/sif_snapshots
#   chmod +x ~/sif_snapshot.sh
#   crontab -e   ->   30 9 * * * $HOME/sif_snapshot.sh >> $HOME/sif_snapshot.log 2>&1
set -euo pipefail
DIR="$HOME/sif_snapshots"
mkdir -p "$DIR"
TMP="$(mktemp)"
curl -sSf --retry 3 --max-time 60 -A "Mozilla/5.0" \
  "https://portal.amfiindia.com/spages/SIF_NAVAll.txt" -o "$TMP"
# sanity: a real file is ~13 KB and starts with the header row; refuse an error page
if [ "$(wc -c < "$TMP")" -lt 2000 ] || ! grep -q "Scheme Code" "$TMP"; then
  echo "$(date -Is) bad download, not saved"; rm -f "$TMP"; exit 1
fi
OUT="$DIR/SIF_NAVAll_$(date +%F).txt"
mv "$TMP" "$OUT"
echo "$(date -Is) saved $OUT ($(wc -c < "$OUT") bytes)"
