# Report — lane 7f — OpenDDIL manual ingest, and two processability arms that disagree

**Date:** 2026-10-16 · **Pin:** `sha256:85ad4c9db2be…` (#97 + #113 + #114 + #116 + #117 on one pin)
**Order:** items 1 (OpenDDIL half) and 3 of the four-item order.
Every number below is measured against the cluster or the installed package.
Nothing here is inferred from a docstring.

---

## 1. The ten MRAD XML drops: DONE, and nobody relaunched them

**They self-executed.** `ingress_user_xml_sensor` carries
`default_status="RUNNING"`, so the moment #97 went live on this pin the sensor
listed a prefix it had never seen (no cursor) and fired **eleven**
`xml_graph_sync_job` runs at 04:30–04:44Z. No manual relaunch was performed or
needed.

| Runs | Outcome |
|---|---|
| 10 | **SUCCESS** — all five stages |
| 1 | FAILURE — `rev188-door-probe.xml`, declared kind `xml` |

**Which stages they reach: all five**, per successful drop —
`extract_rdf_from_xml` → `upload_to_jena` → `index_xml_chunks_to_weaviate` →
`init_neo4j_n10s` → `sync_jena_to_neo4j`. Per run: 8 triples to Jena, 2 chunks
to Weaviate, n10s ready, Neo4j synced.

**The one failure is the halt working.** The probe declares kind `xml`, which
**no** arm of this image can run, and it halted naming that reason. Not a gap.

**Flagged, not fixed — the ten drops are six distinct DMCs.** Four were dropped
twice with different content shas, so the graph now holds the same data module
under two `urn:doc:` named graphs. That is an identity/supersession question
(which wins? does the older graph get retracted?) and it belongs to the
architect, not to this lane.

## 2. The five PCN drops: they fired long ago, and all five died on the ADR-0041 guard

They were never waiting for a launch. `ingress_user_sensor` has launched **12
runs in its life: 7 SUCCESS, 5 FAILURE** — and the five failures are exactly the
five drops whose manifest declares no `content_kind` (three on 10-06, one on
10-11, one on 10-12).

All five failed at the single op `process_user_document_artifact`, same cause:

> `ValueError: ADR-0041 guard: sidecar '<prefix>/manifest.json' carries no
> domain_type (got None) AND no registered content_kind (got None). … the
> registered kind's row is what declares the domain, so a drop needs a kind the
> table knows. Registered kinds: ['doors-export', 'engineering-document',
> 'pcn', 'pdf', 'pdn', 's1000d-data-module', 'work-instruction', 'xml'].`

**Which stages they reach: none.** The guard raises before any artifact is
written. It is a *designed* refusal that names the sidecar, both missing fields,
the registered set and the remedy — not a crash.

This also **closes an open mechanism** from 2026-10-06, where a null
`domain_type` drop (PCN26-117) succeeded and contradicted the recorded halt. The
guard is `domain_type` **OR** a registered kind; PCN26-117 passed because its
kind `pcn` is a registered row and the row declares the domain. The two
observations were never in conflict.

### Lane 1: correcting the manifests in place will do nothing

Three independent reasons, each measured:

1. **The run_key is already consumed.** `run_key = f"{ETag}-{obj_key}"`
   (`dag_tools/components/s3_sensor/sensor_component.py:116`). A FAILED run
   consumes its key permanently — only `NOT_STARTED` falls through to a launch,
   and there is no time window. Same ETag + same key ⇒ silently skipped.
2. **A manifest rewrite is not a trigger.** `manifest.json` is in the
   component's `filter_patterns`, so it never becomes a candidate object. The
   payload PDF is untouched, so its ETag does not move either.
3. The retry path that exists for this — `ingest_retry_sensor`, which mints a
   fresh run_key namespace with an attempt counter — has launched **0 runs**,
   because it polls `GET /ingest/retries` and Lane 1 has not shipped it. Every
   tick is a named skip (`404: not deployed yet`).

**What will work:** re-drop the five payloads under a **new object key** (new sha
prefix) with `content_kind` declared in the sibling manifest — `pcn` for the four
notices. Ordering is not an obstacle: the sensor cursor is a **LastModified**
watermark, not a lexicographic one (`dagster_aws.s3.sensor.get_objects` sorts by
`LastModified` and slices after the cursor object), so a re-drop is listed
whatever its key sorts like. Alternatively, ship `GET /ingest/retries` and the
retry sensor relaunches them with no re-drop at all.

### Severe, incidental, and worth a guardrail

`get_objects` raises `Exception("Provided since_key is not present in list of
objects")` when the cursor's object is absent. The cursor is set to the last key
seen. **So deleting, moving or lifecycle-expiring an object in a watched prefix
makes every subsequent tick of that sensor raise — it lists nothing, for ever,
until the cursor is reset.** This is the shared component: it holds for all four
ingress sensors and for `manufacturing/`, `sustainment/`, `iads/`, `40051/` and
`doors/`. Tidying a watched prefix is a destructive act on the sensor. No
guardrail exists today.

## 3. `GET /kinds/processable` — built, green, and it exposes a disagreement

Branch `feat/processable-kinds-route`. 16 tests pass in
`tests/test_kinds_route.py`; 28 in the two registry suites; 58 across the four
xml/ingress suites.

**Why it must be served by this image**, measured rather than assumed: the
gateway cannot import `doc_tools` (not a dependency of it); the SDK's
`ContentKindRegistration` is `extra="forbid"`, so no registration row can carry
the flag; and processability resolves through the live dispatcher, so any cached
copy goes stale against the image that would run the pass.

**No new dependency.** `starlette` and `uvicorn` were already installed
transitively (via `mcp`); `fastapi` is **not** (the SDK moved it behind a
`[server]` extra). Being transitive is exactly the undeclared-`fastapi` defect,
so both were **declared** with `uv add` — 2 files, +6 lines.

### The finding this route exists to not repeat

`content_kind.processable_kinds()` **excludes** `s1000d-data-module`, because its
declared pass is a class and `dispatch.resolve_python_pass` refuses a class by
contract. But `xml_ingestion._INGRESS_USER_PARSERS` **routes that kind to that
same class** — and ten ODMRAD data modules completed all five stages through it
on this pin, as §1 records.

A door served `processable_kinds()` alone would have been told an S1000D data
module cannot be processed, ten minutes after ten of them were ingested end to
end. **This disproves the "both exclusions are CORRECT" claim in #97's
docstring** — correct about that arm; false as a statement about the image.

So the payload publishes the **union** as `kinds`, plus a named `arms` map
(`python_pass_dispatch`, `ingress_user_xml_parsers`), so a consumer can see which
path a kind takes and the disagreement stays visible instead of being averaged
away. `excluded` lists only kinds **neither** arm can run, each with a reason
code and a detail that says so explicitly.

Exclusions on this tree: `cad` → `unbuilt_pass` (row landed ahead of its pass,
#114), `xml` → `unbuilt_pass` (the live case — the door probe declared it and
halted). `s1000d-data-module` is **not** excluded, because an arm routes it.

**Also found: three XML builders no user drop can reach.** `xml_ingestion`
imports `DitaGraphBuilder`, `IadsGraphBuilder` and `MilStd40051GraphBuilder`, but
the user-drop table routes only S1000D. Their own sensors reach them;
`ingress-user/xml/` cannot. Real gap, flagged, not closed here.

### Auth: refuse what can be judged false, mark what cannot

`verify_bearer` **never raises** — it returns a named reason. Two of those
reasons (`no-verification-key`, `pyjwt-missing`) mean *this pod cannot judge the
token*, not *the token is bad*, and no verification key is configured on this
deployment. A flat "unverified ⇒ 401" would therefore refuse Lane 1's door
holding a **genuine** mint. So: `undecodable`/`invalid`/missing-claim ⇒ 401 under
either posture; `absent` ⇒ served and marked `anonymous`; unjudgeable ⇒ served,
marked `unverified:<code>`, and logged at WARNING. Every response carries
`X-Mesh-Auth`, because a tolerated anonymous call that nothing records is a path
nobody ever fixes. Under `REQUIRE_TRANSPORT_AUTH` anything short of `verified` is
a 401 — with `/healthz` exempt **before** the posture check, so a REQUIRE flip
cannot 401 the kubelet probe and kill the pod it was meant to protect.

### Not done, and it needs a decision

The route is **not wired into any chart** and no server has been started. The
deployment shape is an open question for whoever owns the chart: a second
container + port on the `doc-tools` Deployment, or a separate Deployment. That
and the production auth posture are the two things standing between this and
Lane 1 being able to call it.

## 4. The three fires on this pin: FAIL, and the crop seal is what fails

Job `pcn-gate-85ad4c9d`, 04:37:20Z → 07:04:48Z, pod exit 1.
**Verdict FAIL** — "at least one fire did not exit 0 (parts/crop-seal gate not
met)". The strict verdict is FAIL too.

**Identity: match.** Measured digest == `sha256:85ad4c9db2be…`, and *expected by
pods* → **match**. This is the gate measuring the chart's own pin, not a
coincidence of tags. `DOC_TOOLS_PIN_NOTE`: not set.

**Corpus: 10 distinct documents, 10 scored entries, harness parts 522, distinct
parts 522.** `gt == distinct`, so no document is counted twice on this pin.

| fire | exit | wall | parts | missing |
|---|---|---|---|---|
| 1 | 1 | 2872.1s | **522 / 522 exact** | 0 |
| 2 | 1 | 3102.8s | 505 / 522 | 17 |
| 3 | 1 | 2847.9s | 521 / 522 | 1 |

**Every missing part is `onsemi_Generic_IPCN25300X.pdf`** — fire 2 scored 2 of
19 on it (17 missing NSR/SNSR MPNs), fire 3 scored 18 of 19 (missing
`NSR02F30NXT5G`). No other notice lost a row in any fire.

### Fire 1 was parts-perfect and still exited 1 — so the seal is the block

This is the discrimination that matters, and it holds for **all three** fires,
not just fire 1. The crop-seal block is **byte-identical in every fire**:

```
TOTAL tables=37 stored_cut_tables=2 stored_cut_words=17 repaired_cut_tables=1 repaired_cut_words=16 errors=0
EDGES stored    left=0t/0w top=1t/4w right=1t/1w bottom=1t/12w
EDGES repaired  left=0t/0w top=1t/4w right=0t/0w bottom=1t/12w
FAIL IDT_PDN_OV-19-05.pdf p1 box=(50.8, 117.3, 553.1, 505.7) cut_by=top,bottom
```

Same notice, same page, same box to one decimal, same cut words, same totals,
three times. **The seal is deterministic where parts are not** — it belongs to
the page geometry, not to the sampling. The repair pass works and is not
enough: it recovered the one right-edge word (`right=1t/1w` → `0t/0w`, the TI
table) and recovered nothing at top or bottom, so `IDT_PDN_OV-19-05.pdf`
remains cut through the glyphs at both edges — 4 words off the top
(`PRODUCT DISCONTINUANCE NOTICE (PDN)`) and 12 off the bottom.

So the exit codes decompose cleanly: **the seal fails all three fires; parts
additionally fail 2 and 3.** A fire can therefore never reach exit 0 on this
corpus until the IDT crop is fixed, regardless of how the vision pass samples.
This is the systemic crop-clipping finding, now pinned to one notice, one page,
and one box on this pin.

### Rates: per-fire for the first time, and the fires disagree

#116 is live, so this is the first report whose `rates` block is an aggregate
rather than silently fire 1's:

```
MAXIMA across 3 fire(s)
  needs_review          4 of 10 (40.0%)  from f2
  crops_near_cap        0 of 10          from f1
  crops_row_short       1 of 10 (10.0%)  from f3
  text_layer_degraded   3 of 10 (30.0%)  from f1
!! FIRES DISAGREED on the same image in the same invocation
     needs_review     f1=3  f2=4  f3=4
     crops_row_short  f1=0  f2=0  f3=1
```

That disagreement banner is the instrument working: on the previous
instrument, `crops_row_short` would have been published as **0** because fire 1
saw 0, and the one fire that saw it would have been invisible.
`written_without_vector`: not observed.

### Headers

Agreement exits 1: **8 of 10 agree**; two disagree, and both are **exempted**
(`needs_review=True` in all three fires):

- `TI_PCN_20210316000.pdf` — `mfr`/`mfr_source`: `'TEXAS INSTRUMENTS'` |
  `'Texas Instruments Incorporated'` | `'Texas Instruments Incorporated'`.
  The misformat is present on this pin, at 1 of 3 rather than its measured 5
  of 6 — it is not deterministic, so this is not evidence the alias set fixed
  it.
- `TYC-PCN-24-210412.pdf` — `doc_level_ltb_date_source`: `'-2024'` |
  `'-2024\n[Unca'` | `'06-JUN-2024'`. The *value* agrees at 2024-06-06 in all
  three; only the source string varies.

Header correctness: fire 1 **7 of 9**, fires 2 and 3 **8 of 9**, `clean: True`
in all three. Fire 1's extra miss is the TI `mfr` alias, which scores as
correct-but-not-exact.

### What the five merges did to the score: nothing, as predicted

The provenance entry for this pin predicted the parts score would be unchanged
because none of #97/#113/#114/#116/#117 touches extraction. Fire 1 reproduces
a perfect 522/522, and the entire spread across fires is the known
`onsemi_Generic_IPCN25300X.pdf` instability. #116 fixtured that orphan row as
stochastic — a test fixture, not an extraction change — so fire 2 losing 17
rows is the same stochasticity now documented, not a regression and not a fix.

### Published, and the gate is unsuspended

The job published on its own: `latest.json` and
`report-2026-10-16T070441Z.md` to `corpus-gate/nightly` as `5d6bdc07900e`
(verdict fail), PR **#110**. The timestamped filename sidesteps the dated-archive
overwrite hazard; `latest.json` does not, and has since been overwritten by the
catch-up nightly.

**`doc-tools-corpus-gate` was unsuspended as the first act after the fires
settled** (`suspend: false` confirmed), as authorized. The suspension did its
job: the catch-up run `doc-tools-corpus-gate-29868900` started **07:08:43Z**,
after my fire finished **07:04:48Z** — the two never overlapped, so nothing
contended on the one-model vision endpoint and the witness measurement stands.

## 5. Noted in passing

- An **`iagent` release roll ran concurrently** with these measurements
  (dagster-server tag `76af7b83…`; new webserver + daemon pods at 05:06:17Z).
  Not this lane's action. It retired the webserver pod mid-command; the queries
  were re-run against the replacement. The gate job was unaffected (different
  node, different workload).
- `doc-tools-corpus-gate` was **suspended for this one cycle, as authorized, and
  unsuspended as the first act after the fires settled** — §4 records the
  timings that show the two runs never overlapped.
- **A corrected working assumption, stated because it was wrong in writing.** I
  had been treating the S3 sensor cursor as lexicographic / a `StartAfter`
  bound. It is not: `dagster_aws.s3.sensor.get_objects` paginates the *whole*
  prefix, sorts by `LastModified`, locates the cursor object and slices after
  it. So a re-drop is always listed whatever its key sorts like (which is why
  §2's remedy works), and listing cost grows with the prefix, not with the
  backlog.

## 6. Still owed

**Item 1 is complete** with this report, the pin commit and the pin PR.
Carried out of it:

- **The IDT crop is now the gate's binding constraint.** No fire can exit 0 on
  this corpus until `IDT_PDN_OV-19-05.pdf` p1 stops being cut at top and
  bottom. Deterministic, so it is fixable without chasing a sampler.
- `crops_failed` / `crops_truncated` are still not in `RATE_FLAGS`, and seal
  totals are still not in `latest.json` — this report had to be read out of a
  pod log to state them.
- Item 3's tail: PR **#118** is open and green; the deployment shape and the
  production auth posture are the two decisions it waits on.
- Packets owed: to **Lane 1** (an in-place manifest fix is inert — re-drop
  under a new object key, or ship `GET /ingest/retries`); to whoever owns
  **#97** (its docstring overstates the exclusion as CORRECT); to the
  **architect** (the six-distinct-DMCs-in-ten-drops identity/supersession
  question; the three XML builders no user drop can reach; and that deleting an
  object in a watched prefix bricks that sensor, with no guardrail).
