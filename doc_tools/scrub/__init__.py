"""Batch-fixture scrubbing: the ledger that makes a scrubbed fixture auditable.

Only the ledger contract lives here so far. The tokeniser and the allowlist are
the next links in the chain and are blocked on four rulings (see
``docs/contracts/scrub-ledger.md`` §Policy); the ledger is not, because it
*records* which answer a scrub ran under rather than choosing one.
"""
