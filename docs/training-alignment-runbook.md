# Runbook: training concept alignment (`concepts.normalise`)

**Scope.** Running the TRAINING alignment pass against the sandbox store, and
changing `TRAINING_CONCEPT_ALIGNMENT`. Written 2026-11-09 for the first
`propose` run (PR #218). The pass itself is specified in
[`docs/contracts/training-workbench.md`](contracts/training-workbench.md) §4.7;
this file is the order of operations and the one trap that the contract does not
make obvious.

---

## THE TRAP: the first `on` after `propose` is whole-domain, never per-course

**Rule.** Once a `propose` run has written proposals, the next run that writes
`ALIGNS_TO` must cover the **whole domain**: the fleet script with no
`--course`. Never a per-course run, and never by flipping the pod's switch to
`on` and letting the next ingest do it.

**Why.** A `propose` run writes open `PROPOSED_ALIGNS_TO` and the
CanonicalConcepts they name, and **no `ALIGNS_TO`**. So every canonical it wrote
has no `ALIGNS_TO` member and nothing except open proposals. The normal orphan
sweep (`on` mode) `DETACH DELETE`s exactly that shape (§4.7 "Orphans"). A
per-course `on` run gives `ALIGNS_TO` edges only to the components its Course
teaches, so the sweep at its end deletes **every other Course's** proposal-only
canonicals, and their open proposals with them. A whole-domain `on` run gives
every component its canonical and `ALIGNS_TO` edges first, so nothing a proposal
names is left as an orphan.

Nothing reports this. The run succeeds, and the workbench's review rows for the
other Courses disappear, including any a reviewer had not yet acted on.

**What counts as a per-course `on` run.** Each of these writes `ALIGNS_TO` for
one Course and runs the normal sweep:

- an ingest of a TRAINING deck while the pod has `TRAINING_CONCEPT_ALIGNMENT=on`
  (the per-course call at the end of every ingest);
- `scripts/normalise_concepts.py --course <id>` without `--propose` or
  `--dry-run`;
- `normalise_concepts_job` with `course_id` set and `propose_only: false`,
  `dry_run: false`.

**Safe while proposals are open:** any `dry` run, any `propose` run (per-course
or whole-domain; its sweep takes only canonicals with no relationship at all),
and a whole-domain `on` run.

---

## The switch

`TRAINING_CONCEPT_ALIGNMENT` governs only the per-course run at the end of an
ingest. The fleet script and the job ignore it and take their own flags.

| Value | Per-course run at ingest |
|---|---|
| `dry` (default) | plans and logs, writes nothing |
| `propose` | open `PROPOSED_ALIGNS_TO` and their canonicals; no `ALIGNS_TO` |
| `on` | canonicals, auto and accepted `ALIGNS_TO`, proposals, normal sweep |
| `off` | skipped |

**On an image before PR #218, any value other than `dry` or `off` runs as
`on`.** Check the pod's image contains #218 before setting `propose`.

The fleet script `scripts/normalise_concepts.py` **writes by default**: with
neither `--dry-run` nor `--propose` it is an `on` run.

---

## Running the pass in the pod

Under the sandbox roll lock, after the pod guard (imageID and
`DOC_TOOLS_VERSION` match what was rolled). From the Bash tool, with
`MSYS_NO_PATHCONV=1` so the pod paths are not rewritten:

```bash
export MSYS_NO_PATHCONV=1
kubectl --context edge -n sandbox exec deploy/doc-tools -- \
  /opt/venv/bin/python /app/scripts/normalise_concepts.py --domain TRAINING --propose
```

Swap `--propose` for `--dry-run` to plan without writing. The summary it prints
carries `propose_only`, the plan counts, and seconds per phase.

**Read back after every writing run,** in the same session:

```cypher
MATCH (:Concept)-[p:PROPOSED_ALIGNS_TO {status: "open"}]->(:CanonicalConcept)
RETURN count(p) AS open_proposals;
MATCH (:Concept)-[a:ALIGNS_TO]->(:CanonicalConcept)
RETURN a.status AS status, count(a) AS n;
MATCH (cc:CanonicalConcept {source: "concepts.normalise"}) RETURN count(cc) AS ccs;
```

After a `propose` run on a store that had no alignment yet, `ALIGNS_TO` must be
0 and the open proposals twice the pair count (one row each way). Measured
read-only on 2026-11-09 against the sandbox: 79 pairs, 158 rows, 107 canonicals
named. Re-measure with `--dry-run` before the run if the store has changed.

---

## Order of operations, 2026-11

1. Roll the image containing #218 (doc-tools roll, values diff first).
2. Pod guard, lock, `--propose` whole-domain, read back.
3. The workbench rolls 0.1.9 and reviewers work the open proposals.
4. **Before the pod switch goes to `on`:** a whole-domain `on` run
   (`scripts/normalise_concepts.py --domain TRAINING`, no `--course`), under
   the lock. Count `PROPOSED_ALIGNS_TO` of every status before and after: the
   total must not drop, because reviewed proposals stay as the record. Each
   `accepted` proposal must now have an `ALIGNS_TO {status: "accepted"}`
   beside it (stat `accepted_materialised`).
5. Only then set `TRAINING_CONCEPT_ALIGNMENT=on` and roll. From here every
   component has `ALIGNS_TO` edges, so per-course runs at ingest are safe.

Until step 5, keep the pod switch at `dry` or `propose`.
