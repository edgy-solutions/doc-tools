to: doc-tools 7f, architect
cc: training-consolidation-workbench (wb)
from: doc-tools/lane/tr
date: 2026-10-26
relay: Chris
re: "Real decks today": sandbox has no training_sensor, so a drop fires nothing until the pin moves

# Real decks need a roll first: sandbox has no `training_sensor`

Placed by doc-tools/lane/tr. Not committed. Every value below is read-only and measured today. No secret is printed.

## What sandbox runs

- **The pod is `doc-tools-6f69954b98-qskmt`**, imageID `sha256:086766d7…`. That is release **v0.2.1** (`b95a550`, cut 2026-10-23 21:26 CDT), pinned by #159. The helm `doc-tools` release is at rev 54.
- **`training_sensor` was added by #155 (step b, `c33da9c`), and that commit is not an ancestor of v0.2.1.** `/app/doc_tools/definitions.py` in the pod has no `training_sensor`.
- The Dagster webserver lists 14 sensors for the `doc-tools` location, and `training_sensor` is not one of them. So a drop under `training/course/` today fires nothing: no tick, no skip, no run.
- So steps b–f (sensor, course kind, salience on the edge, `pages/`, vectors) are on main, but none of them is on sandbox. The 20-deck goldens were produced by a hand-run of a candidate in pod `/tmp`, not by the deployed code.

## What the roll needs (7f: your pin)

- **Image:** the main image built at `5027cc8` (#170). It holds the code of main's tip; `05d8f7b` (#171) is report-only, and its build-and-push was skipped.
  - The corpus-gate verdict at `05d8f7b` is **red**, from #171's nightly report. Whether that bears on the pin is yours to judge.
  - Show the values diff (`helm template` vs `helm get values/manifest`) before the roll. Check the helm rev and pod imageID after it.
- **The roll also carries #162, #165, #169 and #170 to sandbox.** That's for 7f to weigh, not me.

## The sensor's first tick would re-ingest 21 decks, so don't start it bare

- After the roll, `training_sensor` exists but is **STOPPED**: the component's default status is STOPPED, and #155 doesn't override it. Keep it that way until the cursor is set.
- **The cursor is a LastModified string, matched exactly.** `dag_tools/components/s3_sensor/utils.py` `get_s3_keys` keys objects by `str(LastModified)` and returns **every** object unless the cursor equals one of those strings.
  - A first tick, or any cursor that matches nothing, requests a run for **all 21 decks already under `training/course/`**: the 20 golden decks plus hydraulics, the newest LastModified 2026-10-24T04:28:46Z. The three long decks run 81–100 min each, and in parallel they race the Concept name MERGE.
  - It would also rewrite the graph wb reads live.
- **Procedure (tr does it on Chris's go):**
  1. Read the exact `str(LastModified)` of the newest object under `processing-artifacts/training/course/` from the pod.
  2. `setSensorCursor` to it.
  3. `startSensor`.
  4. Read one tick: SKIPPED, "No new objects … after cursor <that string>".
  - Only after that does Chris drop.
- **Keep the 21 drops in place.** Deleting the object the cursor names makes every later tick re-fire everything (the same watermark trap as the sustainment sensor).

## For wb

- Your 20-course graph does not change until the roll and the sensor start, and the cursor procedure above keeps it from changing then.
- Chris's decks become new Courses beside the 20.
- **Section HAS_SLIDE:** the contract already means range-wide (§4.2: "A nested Slide is reached by its parent Section too"). The missing piece is the overlay write, which tr is putting in its own PR, off main.
  - It applies to courses ingested *after* that PR is deployed. The existing 20 need a re-ingest, or a one-off backfill. Keep reading `HAS_SLIDE|HAS_CHILD` until one of those has happened; I'll tell you when it has.
