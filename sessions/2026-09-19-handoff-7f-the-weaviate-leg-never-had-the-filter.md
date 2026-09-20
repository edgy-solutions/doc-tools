# HANDOFF — doc-tools lane 7f, 2026-09-19 late: the Weaviate leg never had the filter

    to:        c:\Users\cnogr\git\doc-tools  ::  lane/7f          (worktree :: branch)
    cc:        the architect · ia-74/lane/74 [bd26bdc1] · ia-01/lane/01 (orchestrator) · Chris
    from:      doc-tools :: lane/7f, successor to doc-tools-f6 [5e05c6]
    read-by:   the architect's order of 2026-09-19 late — STAMPED, read in full before anything
               was touched. 74's packet arrived mid-session and is stamped below in §1.

**ROUTING, STILL LIVE, STILL FIRST.** `doc-tools-7f [f76842]` is a DIFFERENT session and is not
this work. Route by worktree/branch. Both my predecessor and 74 led with this; it has now been
led with three times and nobody has been bitten, which is the only evidence it is working.

---

## 1. THE ORDER, DISCHARGED ITEM BY ITEM

### §1 CONFIRM THE READ — **CONFIRMED, in every particular.**

One read, no cluster, at `aa36e41` (the lane head as the order was written):

| what the order claimed | measured |
|---|---|
| Weaviate leg's query selects `?uri a ?type` with NO `FILTER(!isBlank(?uri))` | **TRUE** — `ontology_assets.py:1152` (query opens), `:1159` (the triple pattern). The only `FILTER` is the `?type IN (owl:Class, rdfs:Class)` one. |
| no BNode check before `sync_ontology_to_weaviate` | **TRUE** — the `for row in qres` loop at `:1169‑1175` appended every row unconditionally. `sync_ontology_to_weaviate` (`:663`) adds none of its own. |
| Neo4j leg has both | **TRUE** — `:1649` SPARQL, `:1673` `isinstance(row.uri, rdflib.term.BNode)`. The order's line numbers were exact. |
| `partition_ontology_classes` excludes meta-ontology rows and response shapes, never blank nodes | **TRUE** — `:437`, the `if/elif/else` has exactly two exclusion reasons. It is not a third layer and never was. |

**74 ran the same read independently and reached the same answer** (their packet §0, now committed
to `sessions/`). Two readers, separately, same source, same conclusion. The architect's read was
the third.

### §2 FIX THE WRITER — **done, `a8e2b3e`, writer only, no store touched.**

Both layers mirrored into the Weaviate leg, and the test extended to ask BOTH legs.

**The test half is the more important half.** `tests/test_ontology_assets_blank_node_filter.py`
was GREEN for the entire three months the leak was open, and could not have been otherwise: its
drift guard searched the WHOLE MODULE for `FILTER(!isBlank(?uri))`, so the Neo4j leg's copy
satisfied an assertion about a leg that did not have one. **A guard that can be satisfied by a
different function than the one it is about is not a guard.** `_leg_source()` now slices each
function's own body; every assertion is per leg.

Measured, both directions, by deleting one line at a time and running the file:

    delete the Weaviate FILTER  ->  2 failed
    delete the Neo4j FILTER     ->  1 failed  — AND THE OLD MODULE-WIDE GUARD STAYED GREEN,
                                    live, in front of me, demonstrating exactly the blindness
    neither                     ->  11 passed

### §3 READ, DON'T RUN — **the architect's guess is CONFIRMED. Read, not run.**

> *"If rdflib mints a fresh BNode id per parse, every re-ingest ADDS blank rows instead of
> overwriting them."*

It does. Read in the installed wheel:

    rdflib/term.py            BNode.__new__  ->  value defaults to "N" + uuid4().hex
    plugins/parsers/notation3.py:1793, 1834  ->  self.uuid = uuid4().hex, PER PARSER INSTANCE
    plugins/parsers/rdfxml.py:349,456,522…   ->  bare BNode()

The row uuid is `generate_uuid5(str(uri))`. For a named class that is stable across runs, which
is precisely what makes this sync an idempotent upsert. For a blank node it is not — fresh id,
fresh uuid5, **new row**. Every re-ingest added the blank-node population of every ontology on
top of the last run's instead of overwriting it.

**So the 96.2% is not a level, it is a rate.** It explains the size, as the order suspected, and
it is why closing the writer had to come before any backfill: a delete against a leaking writer
refills on the next prime.

Pinned in a test rather than left in a comment —
`test_blank_node_row_ids_are_not_stable_across_parses` parses one TTL twice and asserts the
named-class uuid5 REPEATS while the blank-node ones are DISJOINT. Pure computation, no store.
The named half is the control: if it ever fails, the mechanism described is not the one at work.

### §4 THE CHAIN TO A SAFE BACKFILL — **Chris's, unchanged, and the order's step 2 now holds.**

    merge PR #1  ->  image builds (ASK WHETHER IT PUSHED — the PR run does NOT: `push: false`,
                     measured by my predecessor at build-container.yml:468 and in the job log)
                 ->  re-pin charts/doc-tools/values-sandbox.yaml:34
                 ->  doc-tools rolls

Until that image runs, a re-ingest writes the dead vector slot **and** re-leaks the blank nodes.
One re-pin now ships fix D and the filter together, which is what putting the filter in PR #1
before the merge was for.

### §5 THE LIVE PARTITION BY `source_ontology` — **skipped, as ordered.** `README.md:129` — **done**, `7fded9b`, its own commit (the order permitted either).

---

## 2. WHAT I FOUND THAT NOBODY ASKED FOR

### (a) 74's §3 guess about the sixteen is REFUTED — by a read they said was mine to do

74 offered, labelled as a guess: *the 16 vectorless real classes are vectorless because they are
text-less — BFO/IOF classes with a label and no definition, so `embed_document` gets an empty
string.* They wrote "I never opened your embed path — that read is yours." I opened it.

**It cannot be that.** `doc_tools/utils/embed.py:embed_document` posts
`f"{DOCUMENT_PREFIX}{text}"` — `"search_document: "` is ALWAYS prepended, so the payload is never
empty even for an empty `text`. And the caller never passes empty text anyway
(`ontology_assets.py`, the batch loop): `safe_label` falls back to the URI fragment when the
label is absent, and the embed input is the humanized label — `BFO_0000002` embeds as
`"BFO 0000002"`. A definition-less class embeds its name; a name-less class embeds its fragment.
There is no path to an empty input.

**So the sixteen are vectorless for some other reason, and the two candidates I can see are both
INFERENCES — flagged as such, neither measured:**

1. **A transient embed failure at write time.** The batch loop catches any `embed_document`
   exception and writes the row WITHOUT a vector, by design, logging a warning
   (`"writing without vector (BM25-only until backfill)"`). Sixteen scattered rows is exactly
   the shape of a gateway hiccup during one ingest. **Testable without a cluster:** find those
   warnings in the Dagster run logs for the runs that wrote them.
2. **A uuid5 collision between two manifest entries.** The predecessor left `IOF_Core twice in
   the manifest, colliding on generate_uuid5(uri)` open with Lane 1. If the same URI is written
   by two entries and the SECOND write's embed failed, `add_object` with the same uuid replaces
   the object — and an `add_kwargs` with no `vector` key **replaces a vectored row with a
   vectorless one**. That would make the two open items one item. Ten of the sixteen are BFO
   upper-ontology classes, which are exactly the classes an import-heavy ontology declares twice.

**I did not measure either. Do not carry them forward as findings.** Candidate 2 is the one I
would test first, because if it is right it changes the backfill's scope and it closes two items.

### (b) 74's §2 about the comment — acted on, `9c3149a`

`derive_missing_class_labels` justified skipping blank nodes partly with *"they are already
excluded downstream"*. That was **true of Neo4j and false of Weaviate** for three months — the
file asserted as settled the exact thing that was broken, in the first place a reader checking
blank nodes would land. It very nearly worked: my predecessor read this file, wrote a handoff
about blank nodes, and still had to be pointed at the second query by the architect.

The claim is now true. It is still rewritten, because **the vague form is what failed**:
"downstream" names no call site, so it cannot be checked and cannot go stale visibly. The
replacement names both functions, dates itself, and points at the per-leg test.

### (c) THE LOCAL SUITE CANNOT RUN ON THIS BOX — pre-existing, not mine, and it will eat your session if you let it

`uv run -- python -m pytest -q -rs` never returns here. I burned real time on it before
instrumenting it. **It is not slow, it is hung**, and the stack says where:

    magic/compat.py:241   mime_magic.load()        <- module-level libmagic load, hangs on win32
      <- unstructured/file_utils/filetype.py:57
      <- doc_tools/utils/extraction.py:5
      <- doc_tools/components/document_parser.py:13
      <- doc_tools/definitions.py
      <- doc_tools/__init__.py:42   `from .definitions import defs`

Because that last line is in the PACKAGE `__init__`, **any** `import doc_tools.anything` drags in
the whole Dagster definitions graph and hangs. **27 of the 40 test files import `doc_tools` at
module level and are therefore unrunnable locally.** CI is Linux with `libmagic1`; it passes
there in ~11s. Timed, for the next person who wonders which dependency it is: rdflib 0.3s,
httpx 0.3s, weaviate 1.3s, dagster 1.0s, dagster_aws.s3 2.4s, dag_tools 0.9s — and
`doc_tools.partitions`, a 13-line module with one dagster import, **timeout**.

**What IS runnable locally, and it is the part that matters here:** the blank-node file imports
`doc_tools` NOWHERE — it reads the asset source as TEXT. That is not luck, it is how the file was
written, and I kept it that way deliberately when extending it. Same for the response-shape file.

    tests/test_ontology_assets_blank_node_filter.py     11 passed in 1.15s
    tests/test_ontology_assets_response_shape_filter.py  8 passed in 0.32s

**There is also a runaway process on this machine that is not mine and which I did not kill:**
PID 39856, `Python311\python.exe -m pytest tests/test_aitool_linker.py -q -p no:randomly`, with
**~161,977 seconds of kernel time** — roughly 45 CPU-hours in a spin. It is a different
interpreter from this repo's `.venv` and a test file I never ran. **Chris: it is probably worth
killing, and it is probably somebody's abandoned session.** I left it alone because killing
another lane's process on a shared box is not mine to decide.

---

## 3. STATE

    branch         lane/7f
    head           8df82ae   (this handoff commits on top of it)
    vs origin      4 ahead + this file — PUSHED, see the addendum
    vs origin/main 9 ahead + this file
    tracked tree   CLEAN

Commits added this session, oldest first:

    a8e2b3e  fix(ontology): the Weaviate leg never had the blank-node filter — both layers,
             and the test now asks both legs
    9c3149a  docs(ontology): "already excluded downstream" was true of one downstream and
             false of the other
    7fded9b  docs(readme): the install command CI declares is `uv sync --locked`, not `uv sync`

    8df82ae  docs(sessions): 74's packet — the Weaviate leg has no blank-node filter,
             and the sixteen                        (74's file, committed unmodified — see §5)

**UNTRACKED FILES I LEFT. NONE ARE MINE**, all predate this session; I staged only by explicit
filename, never `git add -A`:

    C:/Users/cnogr/git/doc-tools/.mcp.json
    C:/Users/cnogr/git/doc-tools/eval_draft.json
    C:/Users/cnogr/git/doc-tools/mfg_corpus_report.json
    C:/Users/cnogr/git/doc-tools/mfg_corpus_report2.json
    C:/Users/cnogr/git/doc-tools/tests/fixtures/            (directory)

Scratch outside the repo, safe to delete:

    C:/Users/cnogr/AppData/Local/Temp/claude/c--Users-cnogr-git-doc-tools/26aef613-591f-4a2f-8f7e-7509d3d46f3e/scratchpad/

---

## 4. MEASURED vs INFERRED

### MEASURED — read or run, this session

| claim | how |
|---|---|
| Weaviate leg had neither layer at `aa36e41` | read, line numbers in §1 |
| Neo4j leg has both | read, `:1649` / `:1673` |
| `partition_ontology_classes` has exactly two exclusion reasons | read, `:437` |
| rdflib mints a fresh BNode id per parse, three call sites | read the installed wheel, cited in §1 |
| named-class uuid5 is stable across parses; blank-node uuid5 is not | RUN — pure computation, no store, now a test |
| deleting either leg's filter turns the extended test red, per leg | RUN, both directions |
| the OLD module-wide guard stays green when the Neo4j filter is deleted | RUN — the blindness, observed, not argued |
| `embed_document` always prepends `search_document: `, so the input is never empty | read `doc_tools/utils/embed.py` |
| the embed input is never empty at the call site either (label falls back to the fragment) | read the batch loop |
| the local suite hangs at `magic/compat.py:241` via `doc_tools/__init__.py:42` | faulthandler stack dump |
| 27 of 40 test files import `doc_tools` at module level | grep |
| PID 39856 has ~45 CPU-hours in a spin | `Get-CimInstance Win32_Process` |

### INFERRED — guesses, labelled

| claim | why it is a guess |
|---|---|
| the sixteen are vectorless from a transient embed failure | plausible from the code's degraded path; **not measured**, the run logs would settle it |
| ...or from a uuid5 collision replacing a vectored row with a vectorless one | same; this is the one I would test first |
| the Weaviate leg is the "second writer" the `:1621` comment counts | 74 inferred it and I agree; the counts are of a different substrate and **neither of us reconciled them** |
| the libmagic hang is purely a win32 condition | the stack says libmagic and CI is green on Linux; I did not try to fix it and did not confirm the mechanism |

### REPORTED TO ME, not measured by me

* 74: 26,239 rows / 25,255 blank / 984 named; 16 named-and-vectorless; 1,299 blank-and-vectorless.
* 74: blank uris in the live store match `^[Nn][0-9a-f]{20,}$` and **some carry an `n…b246`
  suffix — possibly TWO SPELLINGS FROM TWO PARSERS.** This matters for a backfill's predicate and
  not for mine: my filter keys on `isinstance(..., rdflib.term.BNode)`, which is spelling-blind
  by construction. **Anything reading rows back OUT needs the loose pattern, not `N[a-f0-9]{32}`.**

---

## 5. 74'S PACKET — committed, and why by me

74 addressed the commit of their packet to Lane 1 ("this file is yours to commit"). **Lane 1
cannot reach it:** it is a file in THIS worktree, and Lane 1 works in the fleet repo. I committed
it unmodified, in its own commit, with 74 named as its author in the message. Nothing in it was
edited. If Lane 1 wanted it somewhere else too, the content is theirs to copy.

The packet also **withdrew** 74's 16-question blank-node discriminator, on the architect's ruling
that blank nodes do not belong in the index. Nobody should rebuild it.

---

## 6. OPEN, AND WHOSE

| open | whose |
|---|---|
| **PUSH `lane/7f` and let PR #1's checks run on all three commits** | **the next session, or Chris** — see the note below |
| Merge PR #1, then ask whether the image PUSHED, then re-pin `values-sandbox.yaml:34` | **Chris** |
| Backfill of the blank rows already in Weaviate — NAMED ROWS ONLY per the ruling | 74 scopes, **Chris authorizes** |
| The sixteen: build a re-embed path OR rule them legitimately text-less | **the text-less branch is now closed — see §2(a).** Re-scope before anyone builds |
| `IOF_Core` twice in the manifest, colliding on `generate_uuid5(uri)` | ia-01/lane/01 → architect. **§2(a) candidate 2 may make this the same item as the sixteen** |
| A re-embed path (none exists in this repo) | **held until four walks draw** |
| `test_the_imported_sdk_IS_the_pinned_artifact` | **OWED, held until four walks draw** |
| The libmagic import hang / `doc_tools/__init__.py:42` importing the whole graph | **nobody yet.** Not urgent for the cluster; it costs every local session real time |
| PID 39856, the 45-CPU-hour runaway | **Chris** |

**On pushing.** I did not push. My predecessor pushed each commit and left PR #1 green; I have
added three commits to a branch whose PR is open, and the full local suite cannot be run here to
pre-check them (§2(c)). The two files I could run are green with negative controls in both
directions, and nothing I changed can affect a test that does not read those legs — but "cannot
affect" is an argument, and CI is a measurement. **Push and read the checks; do not merge on my
say-so.**

---

## 7. STANDING

* **Nothing touched a shared store.** Zero reads, zero writes, no port-forward, no cluster
  contact of any kind this session. The 96.2% and the sixteen are 74's measurements, carried, not
  re-taken.
* **Writer only, as ordered.** The existing blank rows are NOT deleted and NOT counted. This fix
  stops the next prime adding more; it removes nothing.
* **Nothing re-locked.** `7fded9b` documents the flag CI already declares.
* **Expect the red.** `seal_a_written_row_is_RETRIEVABLE` will still fail every ontology ingest
  until 74's backfill lands. Unchanged by this work, still correct, still not a regression.
* **The session's own finding, and it is the predecessor's finding again from the other side:**
  the leak did not survive because it was hard to see. It survived because *three separate
  artefacts asserted it was already handled* — a comment that said "already excluded downstream",
  a test named for the filter, and a fix commit that closed "the" leak. **Every one of them was
  written by someone who had checked exactly one of the two legs.**


---

## 8. ADDENDUM — the architect's second order, 2026-09-19 late, same night

Everything above was written before this order arrived. Nothing above is retracted; this
section records what changed.

**ACCEPTED as reported:** `a8e2b3e`, the twice-parsed seal inside it, and `7fded9b`.

### §2 PUSHED — and §6's "I did not push" is now HISTORY, not advice

The architect overruled my hold, and the reasoning is worth keeping because my caution was
aimed at the wrong risk: **a lane push publishes only my own commits**, and the PR build runs
`push: false`, so pushing releases no image and moves no tag. The thing I was protecting
against — untested commits reaching something that deploys — was not reachable from a push.

**"Green" for this repo now has a stated definition, and it is the architect's:** green in CI,
at a stated sha, **read step by step — a green run can hide a skipped job.** The overall
conclusion is not the measurement; the per-job rows are. PR #1 is NOT mergeable until it is
green at the pushed sha, and that is said in the PR itself, not only here.

The CI result is reported in PR #1 against the pushed head, deliberately NOT in this file: a
commit to record CI would move the head and invalidate the sha the record is about.

### §3 74's packet — mine, stamped, `8df82ae`

The order giving that commit to Lane 1 is WITHDRAWN, and the reason is the sharpest thing in
the order: **a Lane 1 push on this branch would have released my unpushed commits.** The
packet was the only untracked file in the way, so the tidying act and the releasing act were
the same act. It is worth stating as a general hazard: *a peer committing one file in your
tree is a peer publishing every commit you are holding.* My predecessor's "stage by filename,
never `git add -A`" protects the tree; it does not protect the branch.

The read-by is stamped, the commit is staged by name, and the ONLY edit to 74's file is the
stamp their own header asks for. I left their `cc:` line saying "this file is yours to commit"
untouched: it records what they were told at the time and is not a live instruction.

### §4 ONE LINE BACK — **YES.**

`n<hex>b<counter>` is the Turtle/N3 parser's spelling. `rdflib/plugins/parsers/notation3.py`,
`RDFSink.newBlankNode`, mints `BNode("n%sb%s" % (self.uuid, self.counter))` — `self.uuid` is a
per-parser-instance `uuid4().hex` set in `RDFSink.__init__:1834`, and the counter increments
per blank node in the parse. So 74's "`n…b246`-suffixed" ids are not a suffix at all: `246` is
that parse's 246th blank node.

**Both spellings are the same writer**, differing only by which parser ran: `N<32 hex>` is the
default `BNode.__new__` form that the RDF/XML parser gets from a bare `BNode()`; `n<hex>b<n>`
is what Turtle goes through. **There is no second writer.** And the filter keys on
`isinstance(..., rdflib.term.BNode)`, which is spelling-blind by construction, so it already
covers both — which is the whole reason the Neo4j leg was written that way and the 2026-06-15
string-prefix filter was a no-op.

*Only a tool reading rows back OUT needs a string predicate, and it needs 74's loose
`^[Nn][0-9a-f]{20,}$`, not `N[a-f0-9]{32}`.* The tight pattern misses every Turtle-parsed row
in the store.

### §5 THE SIXTEEN — one line, as asked

**YES: the `IOF_Core` double-manifest collision is a candidate cause** — a second entry
re-writing the same uuid with no `vector` key replaces a vectored row with a vectorless one —
so the sixteen JOIN Lane 1's held item rather than standing as their own. Nothing built.

### §6 THE HUNG SUITE — debt, held. Not touched.

### PID 39856 — killed, on Chris's word

Chris authorized it explicitly; the architect confirmed it was Chris's call and that I was
right not to make it myself. `taskkill /PID 39856 /F` → SUCCESS, confirmed gone. ~45 CPU-hours
of spin, a `Python311` interpreter that is not this repo's `.venv`, running a test file I never
ran. **If a future session finds the box slow, look for this shape before blaming contention.**

Lane: doc-tools/7f
