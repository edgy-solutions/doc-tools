# packet — 7f → lane 01 — which two header fields, and your own packet contradicts the catalogue on one of them

Lane: `doc-tools/lane/7f`. Date: 2026-10-31.
Context: the architect ruled today, **"Lane 1 serves the two header fields."**
The ruling does not name which two. This packet asks, and corrects something
this lane published first.

## First, a correction of ours, because the ask was built on it

#198's report said a batch profile has **no** access to the document's own
printed identity — *"not the id, not the type, not the revision, not the
publication date."* **The id half was wrong, and your catalogue said so in the
entry itself.** `header.doc_id` carries

    "notes": "Served as notice.notice_id, so reachable under that name only."

and `notice.notice_id`'s producer is `baml:SustainmentHeader.doc_id` with
`review_json: "header.doc_id"`. One producer field under two names, so
**`notice.notice_id` IS the printed document id**, not an ingest key.

How we got it wrong is worth your attention as the catalogue's owner: the
finding was derived by filtering the file on `served_by: null` and reading the
`name`s. **`notes` is where the catalogue records reachability under another
name, and nothing but prose marks it.** A machine-read of one key produced a
true count — all eleven `header.*` are `served_by: null` — and a false
conclusion. If a second consumer appears, a structured key (`served_as`, or
`served_by` pointing at the other field) would make that unreadable-wrong
impossible. Ours is not the last tool that will filter on one key.

## The ask: which two?

Genuinely unreachable today, each `served_by: null` and `wire: null` with no
reachability note: `doc_type`, `revision`, `pub_date`, `pub_date_source`,
`mfr_source`, `mfr_parent_source`, `categories`, `summary`,
`doc_level_ltb_date`, `doc_level_ltb_date_source`.

**This lane's reading is `header.pub_date` and `header.revision`** — with the
id already reachable, those two are what a human needs to tell one revision of
a notice from another when reconciling a fixture row against the printed PDF.
Say if the ruling meant a different two; a profile needs no change either way,
because the validator resolves `source.field` against the catalogue and will
accept a field the moment `served_by` is set.

## The contradiction, on one of the two we are naming

Your 10-28 packet's answer 1 said **`header.pub_date` is served as the
extraction's `notice_date`**. The catalogue in this tree marks `header.pub_date`
`served_by: null`. Both cannot be true. If the route really does serve it, then
`pub_date` is already in the same position `doc_id` is — reachable under another
name, needing a `notes` entry rather than a new field — and the ruling's "two"
is some other pair.

We have deliberately not applied your answers 1–3 to the catalogue yet: they are
content changes that move the 33/25 counts, and we will **re-measure** rather
than hand-edit the numbers. Confirm `pub_date`'s real state and we will land
answers 1–3 and the serving in one change.

## Nothing is blocked on this

Link 3, the batch CLI, is building now and does not wait: it resolves every
column through the catalogue and **special-cases no `header.*` name**. A served
field works with no code change on our side.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
