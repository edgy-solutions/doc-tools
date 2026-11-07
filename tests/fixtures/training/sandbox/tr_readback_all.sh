#!/bin/sh
# In-pod, READ-ONLY. Reads back every staged deck once both streams are DONE.
#
#     sh /tmp/tr_run/tr_readback_all.sh
#
# Writes out/runs.jsonl (both streams), out/rb/<slug>.json per deck and
# out/never_written.json over the distinct Course ids (the same-bytes pair is one).
set -eu
D=/tmp/tr_run
for S in A B; do
  grep -q 'DONE rc=' "$D/$S.log" || { echo "REFUSE: stream $S has not finished"; exit 2; }
done
if [ -e "$D/out" ]; then echo "REFUSE: $D/out exists"; exit 2; fi
mkdir -p "$D/out/rb"
cat "$D/runs_A.jsonl" "$D/runs_B.jsonl" > "$D/out/runs.jsonl"
cd /app
ids=""
for k in $(cat "$D/keys_A.txt" "$D/keys_B.txt"); do
  s=$(basename "$(dirname "$k")")
  PYTHONPATH=/app /opt/venv/bin/python "$D/tr_readback.py" "$k" "$D/out/rb/$s.json"
  ids="$ids $(/opt/venv/bin/python -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["ingest_id"])' "$D/out/rb/$s.json")"
done
/opt/venv/bin/python -I "$D/tr_never_written.py" "$D/out/never_written.json" $(echo $ids | tr ' ' '\n' | sort -u)
