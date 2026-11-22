# ADR-0115 — the hold on `playbook` is lifted

**Status:** accepted + built
**Date:** 2026-11-07 (held, ratified and lifted, the same day) · recorded 2026-11-18
**Deciders:** Chris — the hold was this lane's, ratified and lifted in one ruling
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `tests/test_processable_kinds_publisher.py:104-120`
(`test_playbook_is_advertised_and_is_held_by_nothing`); the lifted hold is kept as a comment at
`doc_tools/api/kinds.py:105-118`
**Related:** [ADR-0114](ADR-0114-xml-is-held-out-until-a-drop-proves-it.md) (the hold mechanism
and the failure this one arrived by), [ADR-0232](ADR-0232-the-playbook-kind-seam.md) (the
`playbook` contract's own status line), [ADR-0101](ADR-0101-processable-kinds-are-published-not-served.md)

## Context

`playbook` was held out of the advertised list for one day, and the reason is the exact failure
the `xml` hold predicts — arriving by the other route.

Arm 1 of the processability union claims a kind when every declared pass resolves through
`doc_tools.passes.dispatch`. Building the playbook chunker made `playbook.playbook_outline`
resolve, so arm 1 began claiming the kind, and **this door began advertising it with the whole
suite green**. Nothing in the suite is wired to the advertised list's *membership*, so a kind
entering it is not an event anything observes. The hold predicted by
[ADR-0114](ADR-0114-xml-is-held-out-until-a-drop-proves-it.md) is written against a parser row
being added; this was a pass being **built**, which is a change no one thinks of as a routing
change.

The hold was taken because the splitter rule was wrong at that moment: text under a non-leaf
heading, and text before the first heading, were in no chunk at all, and therefore
unretrievable. Advertising a kind whose content is only partly retrievable tells Lane 1's door
it can route something this image would silently half-ingest.

## Decision

**The hold on `playbook` is lifted: the door advertises the kind.**

- The hold stood **only until the splitter rule was fixed**. That fix landed with the hold
  entry's removal, in the same change, and the ruling is that the door then advertises the kind.
- `playbook` is therefore in `processable_kinds()` and in `ingestable_kinds()`, and in neither
  `HELD_OUT` nor the published `held_out` rows.
- The lift is **pinned positively** — four assertions that the kind *is* advertised and *is not*
  held — not by the absence of an assertion. A kind falling silently out of the advertised list is
  the failure that test file exists for, and the hold that used to keep this one out was a single
  dict entry away.
- The hold's comment is **kept rather than deleted**, because the reusable part is the failure
  mode: a pass becoming real is enough to change what this door advertises, and nothing fails
  when it does.

## Consequences

- Lane 1's door may route `playbook`, and this image's answer for it is honest about
  retrievability: every chunk a playbook produces is reachable.
- Advertising is not the same as a drop seam. The `playbook` row carries `ingress_prefix=None` —
  *"there is no user-drop seam, a playbook arrives by clone, so there is no sensor and nothing to
  advertise a drop path for"* (`doc_tools/utils/content_kind.py:488-489`). A reader who takes the
  advertised list as a list of droppable kinds will be wrong about this one; what the list says is
  that this image can process the kind.
- The `playbook` contract's own status line has not kept pace with that, which is
  [ADR-0232](ADR-0232-the-playbook-kind-seam.md)'s subject, not this record's.
- The one-day hold is the precedent worth keeping: a hold may be taken by this lane and ratified
  afterwards, and a hold with a stated condition can be lifted the same day the condition is met.
  A hold with no condition would still be in place.
- Nothing watches for the *next* kind to enter the list this way. The hold mechanism is a manual
  instrument, and the comment at `kinds.py:105-118` is the only place that says so.

## Alternatives considered

- **Delete the hold comment along with the entry**, since the hold is over. Rejected in the
  comment itself: the entry is gone but the failure mode it documents is general, and it is the
  part a future reader needs.
- **Keep the hold until a measured drop**, as `xml`'s hold requires. Not taken: the two holds
  have different releasing conditions by design, and this one named a code fix — the splitter
  rule — rather than a drop. The ruling that took the hold is the ruling that set that condition,
  and it was met.
- **Leave the kind advertised and fix the splitter afterwards.** Rejected by the act of taking
  the hold at all: for the day between, the door would have offered a kind whose text was partly
  unretrievable, and no instrument would have said so.
