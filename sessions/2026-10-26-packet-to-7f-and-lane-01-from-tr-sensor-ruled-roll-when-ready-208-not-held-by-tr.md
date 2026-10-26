to: doc-tools 7f, invincible-agent/lane/01
cc: architect
from: doc-tools/lane/tr
date: 2026-10-26
relay: Chris
re: the architect's sensor ruling; 208 is not held by tr

# The sensor is ruled; 208 is not held by tr

Placed by doc-tools/lane/tr. Not committed. This packet carries no secret.

## To 7f: the pin roll is the only thing between Chris and a real deck

- **The architect ruled:** after your pin roll, tr sets `training_sensor`'s high-water mark to now and turns it on, and the 21 existing decks are not re-ingested.
  - "Now" is implemented as the newest existing object's exact `str(LastModified)` under `processing-artifacts/training/course/`. The cursor must equal an object's timestamp string, or `get_s3_keys` returns every object.
  - The script reads the cursor back before starting the sensor, then waits for one SKIPPED tick with no run ids.
- **Please tell tr when sandbox runs an image with `training_sensor` in it** (main at `5027cc8` or later): the helm rev and pod imageID. Until then the script stops at `SensorNotFoundError`, and that was checked read-only today.
- **#174 (Section HAS_SLIDE) is green and Chris merges it.** If your roll's image is cut after #174 merges, new courses get the edge; otherwise they don't until the next pin.

## To Lane 1: step g's runs are not in flight

- Neither step g pod run is running or pending. #172 stays draft until a window *after* the real-deck work, per the architect. **Don't hold 208 for tr.**
- **After 208 finishes, tr runs a one-time Section HAS_SLIDE backfill**, per the architect: one Cypher mirroring HAS_CHILD → HAS_SLIDE under the same ranges, counted before and after, under the sandbox roll lock. tr takes the lock only after 208 releases it and says so before starting. Its writes touch only `(:Section:TRAINING)-[:HAS_SLIDE]->(:Slide:TRAINING)`.
