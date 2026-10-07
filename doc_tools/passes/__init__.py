"""Named extraction passes, one module per pass namespace.

A row in ``doc_tools/utils/content_kind.py``'s ``KIND_MAPPING`` declares its
passes as dotted names (``identity.document_identity``). The dotted name maps
literally onto this package: ``<namespace>.<pass>`` is
``doc_tools.passes.<namespace>.<pass>``, a module-level callable.

``tests/test_passes_registry.py`` enforces that correspondence in both
directions, so a declared pass cannot drift from a built one.
"""
