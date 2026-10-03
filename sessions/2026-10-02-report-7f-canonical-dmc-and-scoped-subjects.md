# 7f — rulings 2(c) + 2(d) + §2.4/§2.5, measured

Branch `s1000d/canonical-dmc-and-scoped-subjects`, commit `dde24f6`.
Stacked on `s1000d/classify-fallthrough-count` (PR #53) for content, PR'd to
`main` so CI dispatches.

All numbers below are from `S1000dGraphBuilder` — the builder
`doc_tools/assets/xml_ingestion.py:11,131` wires for `s1000d/` — run over the
six mock OpenDDIL data modules at `C:\tmp\overnight-1002\M6\` and over the
unit fixture. No cluster contact. Nothing written anywhere.

---

## 1. The DMC was not a DMC (2(c))

This is worse than the Phase 0 report stated. Phase 0 said all six built DMC
URIs *differ* from their authored DMC. The stronger fact: the string the
builder emitted is **not a well-formed DMC at all**.

`doc_tools/parsers/dmc_canonicalizer.py` states the governing rule in its own
docstring:

> "same-canonicalizer-both-sides" — the B2 ingest writer and the B3 read path
> (Engine E's `/resolve_dmc`) must use the IDENTICAL function for normalizing
> DMC strings. Two parallel implementations would reproduce the exact
> `n_candidates=0`-when-it-should-match failure that 49a3fdb (the B2 DMC
> string-form fix) just closed at the write layer.

`49a3fdb` closed it on `s1000d_ingest.extract_facts`. **No asset imports
`s1000d_ingest`.** The builder that is wired kept its own inline `"-".join`,
so the failure the rule was named for was never actually closed on the live
path.

| | string | `canonicalize_dmc` returns |
|---|---|---|
| before | `AE-A-32-1-0-00-00-A-520-A-A` | `None` |
| after | `AE-A-32-10-00-00A-520A-A` | itself |

Eleven hyphen groups where the canonical form has eight: `ssc`+`sssc`,
`dis`+`dvar` and `info`+`ivar` each concatenate. The canonical regex is
anchored, so the old form does not match and `canonicalize_dmc` takes its
"honest miss" path and returns `None`.

**Consequence, stated as a consequence and not as a measurement:** a
`/resolve_dmc` query for a data module this builder ingested would have been
unresolvable by DMC. I have *not* exercised Engine E to confirm the 0-candidate
result end to end — the claim here is that the write-side string does not
satisfy the read-side canonicalizer, which is what the table shows. The
end-to-end check is also moot in sandbox for a second reason: no `urn:doc:*`
named graph exists in Jena at all (Phase 0 §5), so the XML path has never
landed a triple there.

### Over the six real modules

| authored DMC | built DMC | matches | round-trips |
|---|---|---|---|
| `DMC-ODMRAD-A-34-10-01-00A-040A-A` | `ODMRAD-A-34-10-01-00A-040A-A` | yes | yes |
| `DMC-ODMRAD-A-34-10-01-00A-320A-A` | `ODMRAD-A-34-10-01-00A-320A-A` | yes | yes |
| `DMC-ODMRAD-A-34-10-01-00A-421A-A` | `ODMRAD-A-34-10-01-00A-421A-A` | yes | yes |
| `DMC-ODMRAD-A-34-10-01-00A-520A-A` | `ODMRAD-A-34-10-01-00A-520A-A` | yes | yes |
| `DMC-ODMRAD-A-34-10-01-00A-720A-A` | `ODMRAD-A-34-10-01-00A-720A-A` | yes | yes |
| `DMC-ODMRAD-A-34-10-01-00A-941A-A` | `ODMRAD-A-34-10-01-00A-941A-A` | yes | yes |

**6 of 6, from 0 of 6.** The architect's 2(c) condition was met before the
change — the live `dmc-` count is 0, so there is no migration to run and the
shape change was free.

The 4.x `disassyCode` / `disassyCodeVariant` spellings are now read, short
forms as fallback, same order as `s1000d_ingest.py:113`. The mock happens to
use the short spelling, so this is not what fixed the six above; it fixes a
4.x document, and it closes a collision where two modules differing *only* in
the disassembly code landed on one URI.

## 2. The content kind reaches the graph (2(d))

Phase 0: zero classified kinds over six modules. After:

| info code | kinds emitted |
|---|---|
| 040A | `DataModule`, `DescriptiveDataModule` |
| 320A | `DataModule` only |
| 421A | `DataModule`, `FaultIsolationDataModule` |
| 520A | `DataModule`, `ProcedureDataModule` |
| 720A | `DataModule`, `ProcedureDataModule` |
| 941A | `DataModule`, `IllustratedPartsDataModule` |

**5 of 6 classified.** The sixth is correct behaviour, not a miss: 3xx has no
`mil:*` class, so it stays the bare root and its fallthrough is **counted** —
the tally over the six runs is `{'3': 1}`, which is PR #53's mechanism firing
on real input for the first time. Adding a `mil:*` kind for 3xx is a TBox
change in `invincible-agent/setup/ontologies/*.ttl` and is the architect's
call, not a row added here.

Both the kind and the root are emitted. The kinds are `rdfs:subClassOf
mil:DataModule` in the TBox, but Jena serves these graphs without reasoning,
so dropping the root would have silently removed classified modules from any
consumer querying `?s a mil:DataModule`.

## 3. Document-scoped subjects (§2.4) and the Tool/Part split (§2.5)

Over the combined six-module graph:

| | before | after |
|---|---|---|
| distinct subjects | 8 | 10 |
| `tool-` subjects | 0 (tools coined under `part-`) | 2 |
| subjects typed BOTH `mil:Tool` and `mil:Part` | 1 | **0** |
| `part-ODM-SE-0001` referenced by | 2 documents, merged | n/a, split |

`mil:part-ODM-SE-0001` was coined by the 520A and 720A modules and merged into
one node carrying both documents' edges. It is now two subjects, each scoped
by `doc_id`. The bare part number stays on the node as `mil:hasPartNumber`, so
"which documents mention ODM-SE-0001" is still answerable — by joining on the
literal, which is a join a consumer performs deliberately, rather than by
subjects silently fusing.

This is also what makes the `doc_id`-keyed rollback the architect kept from
§4.3 possible at all. While part and figure subjects were shared, deleting one
document's subjects would have taken another document's edges with them —
the same shape as the component-IRI finding on the PCN side.

Subject fragments are now scrubbed, preserving `-` and `.`. A part number
containing a space was previously spliced into the URI verbatim, which makes
the Turtle unserializable; there is a test for it.

## 4. What this does NOT do

- **`fig_0` is still named after a loop index.** Document-scoping removes the
  cross-document collision, which was the §2.4 defect. Two unlabelled figures
  within one document still get `fig_0`/`fig_1` and are distinct. A stable
  within-document figure identity is a 2(e) concern.
- **The other three parsers share the unscoped-subject defect.**
  `iads_rdf.py`, `dita_rdf.py` and `mil_std_40051_rdf.py` all coin global
  `part-` / `tool-` / `fig-` subjects. Not touched: the dispatch scopes weeks
  1–2 to S1000D and the 40051 sensor "stays what it is." Recorded here so it
  is not re-discovered as new.
- **No fault-code node, no `dmRef` edge, no parts-list item.** That is 2(e).
  The five content cross-references and the `AM-BIT-017` fault code are still
  in the source and still absent from the graph.
- **Nothing has been ingested.** No MinIO write, no credentials read, no graph
  mutation. The `/ingest` run is a later step.

## 5. Deviation from the dispatch — disclosed

The dispatch lists 2(c), 2(d) and the document-scoping as separate items.
They shipped as **one commit in one PR**, because all three rewrite the same
function (`parse_data_module`) and the same fixtures. Three PRs would have
conflicted with each other, and a stacked PR in this repo gets no CI at all
(`on: pull_request` filters `base: main`), so the alternative was three
unverified changes.

For the same reason this branch is cut from `s1000d/classify-fallthrough-count`
(PR #53) rather than from `main`: the new tests import `FALLTHROUGH_COUNT` and
`reset_fallthrough_count`, which exist only on #53. The PR targets `main` so
CI dispatches and is green; #53's commits appear in its diff until #53 merges,
after which the diff narrows on its own. **#53 should merge first.**

## 6. How it was run

`.venv\Scripts\python.exe` from PowerShell (the Bash tool hangs pytest on
libmagic in this repo; it also hung a repo-wide `grep` on the worktree tree
this session).

- `pytest tests/test_parsers_rdf.py tests/test_xml_ingestion.py
  tests/test_mil_info_code_map.py` → **47 passed**.
- Full suite → **1046 passed, 15 skipped, 4 deselected, 3 failed**. The 3 are
  the pre-existing `test_mesh_sdk_pin.py` `iagent_mesh.provenance`
  ModuleNotFoundError from the stale shared venv (0.9.4 against the v0.9.5
  pin) — unrelated, green in CI.
- The six-module measurement: `scratchpad/verify_2cd.py`, which imports the
  parser through pre-seeded stub `sys.modules` entries so
  `doc_tools/__init__.py`'s `from .definitions import defs` never executes.
  That import — not a bug — is what hung the earlier `check.py` attempt.
