to: architect (via Chris), invincible-agent/lane/01 (ADR-0063 owner), lane/saf
from: doc-tools/lane/7f, 2026-10-28
re: ADR-0063 §1 — the three registry rows. Design only, PROPOSED, no code, no roll.

Findings first, because three of §1's premises do not hold as written and one of
them is already built the other way. Then the rows.

Measured against: `doc_tools/utils/content_kind.py` (`KIND_MAPPING`),
`scripts/generate_kind_registrations.py`, `registry/content_kinds/*.yaml`,
iagent-mesh **v0.9.8** (pinned in `uv.lock`, installed in `.venv`), and
`origin/master` `5cd5c940` of invincible-agent for the seam.

---

## F1. `arrives_as` and `review_shape` are not row fields, and cannot be added

`ContentKindRegistration` is `ConfigDict(extra="forbid", frozen=True)` with
**exactly eight** fields:

    kind, branch, passes, outputs, seeds_workflow, identity_field, refresh, domain

There is no `arrives_as` and no `review_shape`. `extra="forbid"` means a row
carrying either is rejected at construction, not ignored. So §1's
"platform owns kind/domain/arrives_as/review_shape" is only true of
`kind`/`domain` today; the other two would need the SDK model widened first,
and that is platform's change, not a registry row we can write.

Separately, §1's field list omits the two fields our rows actually carry and
that the 2026-10-24 ownership ruling assigns to doc-tools: `passes` and
`outputs`.

## F2. The correct spelling is `branch="event"` — and it already exists

SDK **0.9.7** added branches, `CONTENT_KIND_BRANCHES = ("document", "event")`,
and its docstring says it was answering *ia-01/lane/01's 2026-10-02 packet*. An
event row is a different shape, enforced by `_branch_shape_is_consistent`:

| field | `branch="document"` | `branch="event"` |
|---|---|---|
| `passes` | required, non-empty | **forbidden** |
| `outputs` | required, non-empty | **forbidden** |
| `seeds_workflow` | forbidden | **required** |
| `identity_field` | forbidden | **required** |
| `refresh` | forbidden | optional (`None` = push-only) |

So ADR-0063 should say `branch="event"` and not invent `arrives_as: json`. The
SDK's own worked example is `maintenance-fault-event` with
`identity_field="event_id"`, and it records that `POST /maintenance/events` was
**withdrawn in favour of this**: the seam reads `seeds_workflow` off the matched
registration instead of branching on the caller's URL. Three new per-kind routes
would be re-introducing exactly what that withdrawal removed.

## F3. "Arrive as events, not documents" conflates two channels that are separate by design

The arrival shape and the content kind are two channels on purpose. Platform's
`ingest_status.KINDS` is already `(pdf, cad, xml, event)` with
`FILE_KINDS = (pdf, cad, xml)`, and the comment states `event` is excluded from
`FILE_KINDS` *"so a file cannot be dropped as `event`"*. Its test asserts
`row["kind"] == "pdf"` *"kind stays the file format, unchanged"* beside
`row["content_kind"] == "pcn"`, and says in terms:

> *"KINDS had to widen even though 'event' is not a ContentKind leaf."*

So **`event` is the arrival shape, platform-owned and already present** — not a
value we register, and not `json`. The three new names are CONTENT kinds and
ride in `manifest.metadata.content_kind`. One more consequence worth carrying
into §4: an event's ingest id is its own namespace, `^evt-[0-9a-f]{64}$`, not
the `sha256:` shape a file ingest gets.

## F4. doc-tools cannot project an event row today — this is the real work item

Our `ContentKindEntry` already carries `seeds_workflow` and `identity_field`,
but it has **no `branch`** and **no `refresh`**, and
`scripts/generate_kind_registrations.py` projects *exactly* `kind`/`passes`/
`outputs`. An event row written today would therefore project as
`{kind, passes: (), outputs: ()}`, default to `branch="document"`, and be
**refused** by the SDK for having no passes.

**There are zero event rows in the tree**: all 13 registered kinds are
documents, and `seeds_workflow` is set by none of them. These three would be the
first. The fix is small and it is mine: add `branch` (and `refresh`) to the
dataclass, teach the generator to project them, and extend
`tests/test_kind_registry.py`, which pins the drift. I am not writing it here —
the order says design only — but §1 should not read as though the rows can be
added without it.

Also mine to flag: `extractor_config`, `baml_function` and
`target_ontology_class` are **required positionally** on our dataclass and are
all meaningless on an event row, which stamps nothing. They take `""` with a
comment, exactly as `s1000d-data-module` does for `baml_function`. That
asymmetry is a wart in our dataclass, not in the ADR.

## F5. `passes` being non-empty does NOT block these kinds

"A kind with no pass is not a kind" is a **document-branch** rule. An event kind
runs no pass at all. So §1 needs no deterministic parse invented for FRACAS,
safety or cyber. (If any of the three were ever modelled as a document instead,
the non-BAML precedent is `s1000d-data-module`:
`passes=("s1000d.S1000dGraphBuilder",)` with `baml_function=""`.)

## F6. One `identity_field` cannot hold a compound episode key

`identity_field` *"names which field of the arriving artifact is this Event
kind's identity"* — one field, and the seam dedupes on it. §1's "the OpenDDIL
episode/asset ids as the episode key" is a **pair**. A single field name cannot
express a pair, so either OpenDDIL emits one precomputed composite field or the
key is one of the two. I propose the former, named `episode_key`, and the rows
below assume it. If OpenDDIL will not emit it, this is a blocker on their side,
not a row we can finish.

`on_behalf_of` (§1) is a payload field. There is no slot for it among the eight
and nothing to register — it belongs in §4's provenance ladder.

## F7. Use hyphens, or accept the first underscored kinds in the tree

Every registered kind is hyphenated — `s1000d-data-module`, `work-instruction`,
`engineering-document`, `doors-export` — and the SDK's own example is
`maintenance-fault-event`. §1 writes `fracas_report`, `safety_finding`,
`cyber_indicator`. Underscores would be the first in the registry. Cheap to
settle now and effectively permanent later: a kind rename is invisible to the
registry fingerprint, so nothing downstream would flag the drift. The rows below
use hyphens; say the word and I will flip them.

## F8. A new domain value needs a plugin branch — conditionally

`domain_type=None` is a POSITIVE assertion ("this kind declares no domain"), so
these three, being content-level, each need one. The trap: `semantic_assets.py`
ends its plugin selection in `else: plugin = TrainingPlugin(domain_type)`, so an
unbranched new domain is silently treated as training.

Stated precisely, because it may not fire here: an event row runs no passes and
stamps nothing, so it may never reach that selector at all. But §2's FRACAS
landing (`FailureRecordSet` as a `KNOWLEDGE_DOCUMENT`) **is** a document
artifact, and whatever writes it does reach it. So: if `safety` and `cyber` are
new domain values, each needs its selector branch in the same change that adds
it. Domains are §3 and lane 01's, but the trap is ours to name.

---

## The three rows, proposed

In our `KIND_MAPPING` shape. `branch=` is written as it must read **once F4 is
done**; it does not exist on the dataclass today.

    "fracas-report": ContentKindEntry(
        kind_source_value="fracas-report",
        kind="fracas-report",
        extractor_config="",          # meaningless on an event row
        baml_function="",             # no extraction; cf. s1000d
        target_ontology_class="",     # event rows stamp nothing (outputs forbidden)
        domain_type="maintenance",    # PROPOSED — §3 is lane 01's call
        branch="event",               # needs F4
        seeds_workflow="fracas.record_failure",   # PENDING §2
        identity_field="episode_key",             # see F6
        ingress_prefix=None,          # events POST; they are never dropped (F3)
        file_suffixes=(),
    ),

    "safety-finding": ContentKindEntry(
        ...,
        domain_type="safety",         # PROPOSED, NEW domain — see F8
        branch="event",
        seeds_workflow="engine_s.safety_finding", # PENDING §2/§5 (saf)
        identity_field="episode_key",
    ),

    "cyber-indicator": ContentKindEntry(
        ...,
        domain_type="cyber",          # PROPOSED, NEW domain — see F8
        branch="event",
        seeds_workflow="cyber_watch.indicator",   # PENDING §2
        identity_field="episode_key",
    ),

`passes=()` and `outputs=()` on all three, because the event branch forbids
them. `refresh` omitted: all three are PUSH-only unless OpenDDIL offers a pull
for a fresher episode, in which case it is `RefreshSpec` and needs F4 too.

## Two things §1 should pick up from §2, and one I cannot answer

1. **The FRACAS return event is a fourth kind, or it is not a kind.** §2 says
   corrective action "returns as a mod record — define the return event". If it
   arrives through the same door it needs its own row (`branch="event"`,
   its own `seeds_workflow`); if it is a workflow callback inside the FRACAS
   workflow, it needs no row at all. These are different designs and §1's row
   count depends on which.
2. **`review_shape` per kind has no row to live on** (F1). If review shape must
   be per-kind and declared, that is an SDK model change to request, not
   something §1 can register.
3. **I cannot name the `seeds_workflow` values.** They are the workflows §2 and
   §5 define; mine are placeholders marked PENDING, and the rows are not
   finishable until those names exist.

— lane 7f
