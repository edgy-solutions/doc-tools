"""Batch export profiles: the validator for the column-map vocabulary.

Link 2 of the batch fixture chain, after ``doc_tools/scrub/`` and before the CLI
(link 3, not written). ``profile.py`` refuses a profile that violates
``docs/contracts/batch-column-map.md`` and names every violation; it accepts one
that satisfies it.

Nothing under ``doc_tools/`` imports this package, and there is no exporter: no
code reads or writes a batch export. It validates a profile against the contract
schema and ``registry/export_field_catalogue.json`` and does nothing else.
"""
