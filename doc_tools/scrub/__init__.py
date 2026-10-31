"""Batch-fixture scrubbing: a scrubbed fixture, and the ledger that makes it
auditable.

Four modules, in the order the chain runs:

* ``ledger`` -- the merged contract (``docs/contracts/scrub-ledger.md``): what a
  scrub run must record, and what makes its output committable;
* ``allowlist`` -- the vocabulary that is NOT scrubbed, loaded from
  ``registry/scrub_allowlist.yaml``;
* ``draw`` -- the shape-preserving, deterministic replacement draw;
* ``scrubber`` -- the engine: allowlist first, then shape (design 3.3), with the
  six contract checks measured rather than asserted.

``element_text`` reads an extractor element-text dump into blocks, which is how
the engine is measured on a real notice.

Still missing, and the reason a run of this package is NOT committable today:
PDF rewriting and therefore the ``equivalence_seal``, which is reported
``NOT_RUN``. Nothing under ``doc_tools/`` imports this package -- design 7: the
scrubber is not in the ingest path.
"""
