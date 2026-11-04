to: invincible-agent/seat/architect
cc: Chris, invincible-agent/lane/01
from: doc-tools/lane/7f
date: 2026-11-03
re: playbooks on the existing git-source path — kind row, chunker, citation shape, corpus job

Taking the correction: not a new source mechanism, a new content kind on the path that already
ingests from git. Measured from the tree tonight. No build.

**Your confirmation: ref and credential are there; the row is not.** `DDSIngestionConfig`
(`doc_tools/assets/dds_ingestion.py`) and `RabbitMQIngestionConfig` carry the same six fields,
duplicated field for field — `git_repo_url`, `git_branch` (default `main`), `git_token` +
`git_token_username`, `git_ssl_verify`, `schema_path_in_repo`. The token goes in as
`-c http.extraHeader=Authorization: Basic <b64>`, never in the URL, so a failed clone's stderr
carries no credential. Three qualifications the spec has to absorb:

1. **Not rows** — per-asset Dagster `Config` classes with env-var defaults. No name, no labels,
   no registry. So labels-gate-who-asks and token-in-a-Secret-**by-name** have nowhere to live:
   an env default is global to the code location, not per source.
2. **The ref is a mutable name and no run records what it got** — `clone -b <branch>
   --single-branch`, no `rev-parse`. Per-source staleness as you define it (measured ≠ recorded)
   is therefore not satisfiable today: the recorded ref always equals itself. One
   `git rev-parse HEAD` after the clone closes it, and is the smallest change here.
3. **The glob is half present** — `schema_path_in_repo` is a directory; `**/*.idl` is in code.

**1. The kind row.** `registry/content_kinds/*.yaml` is *generated* from `KIND_MAPPING` in
`doc_tools/utils/content_kind.py` and `tests/test_kind_registry.py` fails on drift — so
`playbook` is a mapping entry, not a hand-written file. The key is the source value (the leaf),
separate from the registered `kind`; `work-instructions` → `work-instruction` is the precedent.
Domain is published separately in `content_kind_domains.json` per the 2026-10-24 ownership
ruling and must be declared: a kind with no domain lands in no domain graph at all. 13 kinds
today, none markdown.

**2. The chunker.** The only chunker in the tree is `doc_tools/utils/xml_chunks.py`, graph →
chunks. No markdown chunker, no heading splitter — this is the one genuinely new component.
Split on ATX headings, one chunk per leaf heading, carry the heading path. **Derive `chunk_id`
from the heading path, not from position:** our section ids are positional today, which is why
a re-ingest merges a second outline instead of replacing the first.

**3. The citation shape — two properties, and one already exists.** `DocumentChunk`, the
collection Engine W queries, declares `text`, `doc_id`, `chunk_id`, `domain`, `page`, `heading`,
`section_id`. So `heading` is there; `{source, path}` are the two to add, both TEXT, and neither
belongs folded into `doc_id`. Unusually, this is live rather than inert:
`_ensure_weaviate_collection` already has an add-missing-properties branch for a collection that
exists, so the schema-correct-in-tree-absent-in-pod shape is closed on this path.

**4. What changes in the corpus job.** Capture the resolved sha; read the kind from the row, not
from the asset; chunk markdown by heading; write `source` and `path` beside `heading`. Nothing
about cloning, auth or globbing changes — the correction's whole point.

**One thing to rule, not assume.** Making the two existing asset configs rows on the same
registry is what buys labels, overlay rows and Secret-by-name, and it is a larger change than
adding a kind: it re-plumbs two live ingests. I would land `playbook` on the mechanism as it
stands and make the row migration its own item, rather than re-plumbing DDS and RabbitMQ under
cover of a docs feature. Retiring the mesh's hard-wired `docs/` source is the same decision.

Build is the first docs item after 0.4.78, ahead of `sections[]`. Nothing here is built.
