#!/bin/sh
# In-pod. Starts the two ingest streams detached and returns at once.
#
#     sh /tmp/tr_run/tr_two_streams.sh <expect_sha> [--dry]
#
# Stream A runs the keys in keys_A.txt (the three long decks), stream B those in
# keys_B.txt (the other 17; the same-bytes pair stays in one stream, so the two
# never write one Course at once). Each stream appends its own runs_<S>.jsonl and
# its log ends "DONE rc=N". --dry runs every guard in tr_run_by_hand.py and
# executes nothing; it logs to <S>.dry.log, so it never blocks the real run.
set -eu
EXPECT="$1"
DRY="${2:-}"
D=/tmp/tr_run
SUF=log
[ "$DRY" = "--dry" ] && SUF=dry.log
for S in A B; do
  if [ -e "$D/$S.$SUF" ]; then
    echo "REFUSE: $D/$S.$SUF exists (that stream already ran)"
    exit 2
  fi
done
for S in A B; do
  nohup sh -c "cd /app && TR_RUNS=$D/runs_$S.jsonl PYTHONPATH=/app /opt/venv/bin/python $D/tr_run_by_hand.py --expect $EXPECT $DRY \$(cat $D/keys_$S.txt); echo DONE rc=\$?" > "$D/$S.$SUF" 2>&1 &
  echo "started $S pid=$! log=$D/$S.$SUF"
done
