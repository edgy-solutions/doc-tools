# Roadmap

Every row here is a **remedy**: the thing that would close a gap in one of this repo's records.
Remedies are here and not in the gaps' statuses because **a gap carries the status of the
condition it describes, and the remedy carries its own** — the architect's ruling of 2026-11-19,
adopting the pub-tools owner's rule, so that `built` on a gap can never be read as "the fix is
built". See the [status vocabulary](README.md#status-vocabulary).

**Nothing here is scheduled, and nothing here is mine to schedule.** `proposed` means written
down as intent and no more: no row has been accepted by a ruling, and no row is in code. One row
is `accepted`, because a ruling does accept it; its status says so and the difference is the
point. A row that becomes code leaves this file for the record it came from, where it will be
`built` with its lines.

**How a row names its gap.** A gap bullet has no id of its own, and this lane is not minting an
id namespace for one ([NE-23](NOT-ESTABLISHED.md) settled that `CO-` and `FL-` are not this
lane's to extend unilaterally). A row names the record and quotes the gap's lead phrase, and the
gap bullet names the row back, so the link reads in both directions without a new id space.

`RM-` is this repo's prefix. The shape follows lane 02's structured-fields packet §4.2, which
asks for roadmap rows as `RM-` records with `depends_on` naming `RM` ids. The prefix and the
`depends_on` spelling take lane 02's ruling if it differs ([F-15](../adr/FOLLOW-UPS.md)). This
file is a table, not one record per remedy, because §4.2 is explicitly lower priority and a
sixteen-file expansion of it would be work nobody asked for.

| Id | Remedy | Closes | Status | Depends on |
|---|---|---|---|---|
| RM-01 | A check that compares a written parse body against the object's size or ETag, so a mock body cannot pass as a short document | [CO-EXTRACT](components/extraction-pipeline.md), "A failed download substitutes a mock body" | `proposed` | — |
| RM-02 | A page cap and a memory bound on the parse path, and a non-empty `resources` in the chart | [CO-EXTRACT](components/extraction-pipeline.md), "No page cap and no memory bound" | `proposed` | — |
| RM-03 | Widen the registry fingerprint past `(kind, passes)`, so a renamed mapping key or a changed `domain`, `arrives_as` or `review_shape` compares unequal across two code locations | [CO-EXTRACT](components/extraction-pipeline.md), "The fingerprint cannot see a field rename" | `proposed` | — |
| RM-04 | The measurement the 2026-10-16 hold names as its own lifting condition: a bare `xml` drop processed by a user-drop sensor | [CO-EXTRACT](components/extraction-pipeline.md), "`xml` is advertised by one arm and held by the hold list" | `proposed` | — |
| RM-05 | Make a registry row say which of its passes actually run on the sustainment path, so the declared tuple and the dispatch either agree or differ readably | [CO-EXTRACT](components/extraction-pipeline.md), "The declared `passes` tuple and what executes diverge" | `proposed` | — |
| RM-06 | A test pinning the unknown-alignment-mode branch, so the value that turns writing on cannot change unobserved | [CO-ONTOLOGY](components/ontologies-and-alignment.md), "An unknown alignment mode turns writing on, untested" | `proposed` | — |
| RM-07 | A counter or an asset check that surfaces an alignment failure, so a course whose alignment failed is distinguishable downstream from one with nothing to align | [CO-ONTOLOGY](components/ontologies-and-alignment.md), "Alignment never raises, so a total failure is a log line" | `proposed` | — |
| RM-08 | A comparison across the three stores: Jena against Neo4j, and either against Weaviate's class rows | [CO-ONTOLOGY](components/ontologies-and-alignment.md), "Three stores can disagree and nothing compares them" | `proposed` | — |
| RM-09 | A cross-note in `content_kind.py` and in `ontology_assets.py`, or a rename, reconciling the two authorities that both end `mesh#`. A rename is cross-repo and is not this lane's call; a cross-note is not, and is the cheaper half | [CO-ONTOLOGY](components/ontologies-and-alignment.md), "Two authorities share the local name `mesh`" | `proposed` | — |
| RM-10 | A script, chart template or test that reads the `sandbox/roll-lock` ConfigMap, so the lock is verified by something rather than asserted by an operator. **Closes two gaps**, the convention and the pre-fire helper, which is why a remedy is not one per bullet | [CO-CORPUS-GATE](components/corpus-gate.md), "The roll lock is an operator convention" and "The pre-fire helper does not check the lock either" | `proposed` | — |
| RM-11 | Correct the three duration figures in code to the measured 2h22m–2h34m per fire, or delete them and cite the design document | [CO-CORPUS-GATE](components/corpus-gate.md), "The durations written in the code are stale" | `proposed` | — |
| RM-12 | A check that fails a run when `extraction.json` or `review.json` was not written, rather than logging the storage error and succeeding | [FL-REVIEW](flows/document-to-review-record.md), "Two writes on this path fail silently" | `proposed` | — |
| RM-13 | Correct the `dagster_resources.py:247` docstring, which still calls the posting seam a no-op that logs | [FL-REVIEW](flows/document-to-review-record.md), "A stale docstring says the stage seam only logs" | `proposed` | — |
| RM-14 | Close the third echo door in `semantic_assets.py`, so a BAML exception string stops reaching a person's failure detail | [FL-REVIEW](flows/document-to-review-record.md), "One echo door is still open" | `accepted` — the 2026-11-18 ruling accepts it, which is why this row is not `proposed`. **Owned by lane tr**, whose test pins the current message deliberately; packeted, not changed here | — |
| RM-15 | The formal `asset_check` for the `needs_review` count that the code itself names as a follow-up | [FL-REVIEW](flows/document-to-review-record.md), "A `needs_review` count has no asset check" | `proposed` | — |
| RM-16 | A step that reconciles the three sinks for one document, so a graph write without an index write is visible | [FL-REVIEW](flows/document-to-review-record.md), "Nothing reconciles the three sinks for one document" | `proposed` | — |

## Gaps with no row here

Three gaps name no remedy, and this file does not invent one for them. `proposed` means intent
that is written down; writing intent down in order to have a row to point at would make the
status false.

- [CO-ONTOLOGY](components/ontologies-and-alignment.md), "One course's re-ingest can remove an
  alias another course asserted" — the record says in terms that whether the keying is the wanted
  behaviour is a question for the contract's owner and not a defect this record declares. A
  remedy would presume the answer.
- [CO-CORPUS-GATE](components/corpus-gate.md), "A fire's `stats` keys are observable only while
  the pod exists" — `built` by construction. Persisting more of a fire's output is imaginable,
  but nobody has asked for it.
- [CO-ONTOLOGY](components/ontologies-and-alignment.md), "The vocabulary's drop path is in
  another repo" — what a re-ingest removes is not established from this tree at all
  ([NE-26](NOT-ESTABLISHED.md)), so there is nothing here to remedy yet.
