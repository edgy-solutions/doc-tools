# ADR-0103 — substrate priming lives in the platform chart, not here

**Status:** built
**Date:** 2026-06-17 (`setup/setup_env.py` retired, priming unified into the platform chart) ·
recorded 2026-11-18
**Deciders:** this repo's standing agent guidance (`AGENTS.md` §Workflow Guide 0); no individual
decider is recorded
**Pin:** `2b9e6cbc61178f7086cceade8614dca4d736150a`
**Source:** `AGENTS.md:54` (§Workflow Guide 0); `README.md:113` and `:446`;
`doc_tools/assets/ontology_assets.py:418-425`. The owning side is another repo's:
`invincible-agent/setup/prime_databases.py`, run by that chart's `primeSubstrate` Job
(`invincible-agent/helm/invincible-agent/templates/prime-substrate-job.yaml`)
**Related:** [ADR-0110](ADR-0110-the-platform-owns-a-kind-doc-tools-owns-its-passes.md),
[ADR-0144](ADR-0144-the-vocabulary-path-appends.md),
[ADR-0148](ADR-0148-one-mil-namespace-across-parsers.md), and
[FOREIGN.md](FOREIGN.md) for the externally-owned half

## Context

Neo4j constraints, Weaviate collection schemas, the Jena dataset and the foundational ontologies
all have to exist before a single Dagster sink adapter runs. doc-tools used to prime them itself,
from `setup/setup_env.py`, and it used to host the custom TBox extension TTLs (`mro_extension`,
`maintenance_extension`, `mil_extension`, `idp_extension`, `mesh_system`).

That arrangement had a concrete failure: **priming depended on reaching doc-tools by URL to fetch
the TTLs.** The platform could not prime its own substrate without a running doc-tools to serve
ontology source, so a cold start had a cycle in it. The TTLs moved to
`invincible-agent/setup/ontologies/*.ttl` on 2026-06-17 to cut that coupling, and the priming
script went with them.

The live risk now is the *repair* someone makes without knowing this: adding a TTL back "so the
classes are in the repo that uses them", or a small priming script "so the test environment comes
up". Either one re-creates the coupling the migration removed, and the TTL copy creates something
worse — a **second master**.

## Decision

**Substrate priming is the platform's. doc-tools hosts no priming script and no ontology source,
and must not grow one.**

- Priming — graph constraints, vector schemas, Jena dataset provisioning, canonical ontology
  ingestion — is `invincible-agent/setup/prime_databases.py`, invoked by that chart's
  `primeSubstrate` post-install/post-upgrade Helm Job.
- **Run the platform chart first:** `helm install/upgrade` with `--set
  primeSubstrate.enabled=true` *before* deploying doc-tools, or the sink adapters fail against
  unindexed databases.
- To add or change a class (for example a new `mil:*` content kind), **edit the TTL in
  invincible-agent and re-deploy that chart.** Do not add a TTL or a priming script back here.
- Measured at the pin: **no tracked `.ttl` file in this repo and no tracked file under `setup/`.**
  The only TTLs on disk are untracked scratchpad working copies.
- The manifest of canonical TTLs (`CANONICAL_TTL_MANIFEST`) also stays there. The seal in
  `ontology_assets.py` is deliberately derived from *what the run was handed*, per partition, and
  not from a local copy of the manifest, because a copy would be a second master: the seal would
  be complete against its own copy and blind to the entry that exists in only one of them, and
  the copy is invisible to both repos, so neither side reds (`ontology_assets.py:418-425`).

## Consequences

- A cold start is **two deploys in order**, and the order is load-bearing. There is no in-repo way
  to bring doc-tools up against an unprimed substrate.
- doc-tools is still the *ingester* of ontologies — the priming script hands them over. The
  platform's `trigger_ingest_jobs` passes the semantic domain in Dagster config, and its
  `upload_canonical_ttls` sets `x-amz-meta-domain` on the object; our asset reads config first,
  object metadata second, and **errors rather than deriving a domain from the path**
  (`ontology_assets.py:1165-1174`). Path derivation was removed as a silent fallback precisely
  because it produced confidently-wrong routing for `mil/`.
- A class change is a **cross-repo change with a chart roll**, not a file edit here. That is the
  price of one master, and it is why a reader looking for a class definition in this tree finds
  nothing: the URIs appear in our parsers as strings only
  (`doc_tools/parsers/mil_40051_ingest.py`, `doc_tools/parsers/s1000d_ingest.py`).
- `setup/` is left as an empty directory rather than deleted, so the history of where the script
  lived is not lost on a reader of the tree. `README.md:113` says what it used to hold.
- Our ontology-ingest assets depend on another repo's script's behaviour (which config key, which
  object metadata header). That dependency is named in [FOREIGN.md](FOREIGN.md) rather than
  carried as an assumption.

## Alternatives considered

- **Keep priming in doc-tools.** Rejected by the migration: it made priming depend on a doc-tools
  URL, so the platform could not prime without us. No measurement of the failure is recorded —
  the coupling is the stated ground.
- **Keep a copy of the TTLs (or of `CANONICAL_TTL_MANIFEST`) here for convenience.** Rejected
  explicitly in `ontology_assets.py`: a second master is drift that neither repo can see.
- **A doc-tools chart hook that primes the parts doc-tools needs.** Not recorded as considered.
  The obvious shape — a small pre-install Job in `charts/` — would split ownership of the
  substrate across two charts, which is the condition the 2026-06-17 unification removed. It is
  **not** recorded as weighed.
