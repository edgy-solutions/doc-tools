#!/usr/bin/env python
"""Scrub an extractor element-text dump into a fixture text layer and its ledger.

Run it from PowerShell on this repo's venv interpreter, never a bare python:

    $env:SCRUB_BATCH_SALT = '<the salt>'    # never an argument
    & .\\.venv\\Scripts\\python.exe scripts\\scrub_document.py `
        --element-text tests\\fixtures\\sustainment\\diodes_rev1_eol_text.txt `
        --fixture-id diodes-rev1 --out-dir C:\\tmp\\scrub-out `
        --salt-env SCRUB_BATCH_SALT --salt-ref <secret key NAME>

Writes ``<out-dir>/<fixture-id>.txt`` and ``<out-dir>/<fixture-id>.ledger.json``.

* The salt is read from the NAMED ENV VAR and only ``len=N sha256:XXXXXXXX`` of
  it is ever printed. ``--salt-ref`` is the NAME of the secret, recorded in the
  ledger.
* The script exits 1 when the ledger is not committable. An offline tool that
  exits 0 on a non-committable scrub is how a half-scrubbed fixture gets
  committed. Today that is ALWAYS the case: this engine produces a text layer,
  and the equivalence seal needs a PDF.
* ``--allow-unclassified`` turns ``strict`` OFF, which makes the leak test
  WEAKER: part-shaped tokens in blocks that declare no class are then left in
  the text without refusing the run. The unclassified count is printed either way.
* Nothing under ``doc_tools/`` imports this script (design 7: the scrubber is
  not in the ingest path).
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_ALLOWLIST = os.path.join(ROOT, "registry", "scrub_allowlist.yaml")




def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--element-text", required=True)
    ap.add_argument("--fixture-id", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--salt-env", required=True,
                    help="NAME of the environment variable holding the salt")
    ap.add_argument("--salt-ref", required=True,
                    help="NAME of the secret holding the salt (recorded in the ledger)")
    ap.add_argument("--known-mpns", help="file of one real MPN per line")
    ap.add_argument("--allowlist", default=DEFAULT_ALLOWLIST)
    ap.add_argument("--allow-unclassified", action="store_true",
                    help="strict off: WEAKENS the leak test")
    args = ap.parse_args(argv)

    from doc_tools.scrub.allowlist import Allowlist
    from doc_tools.scrub.element_text import read_blocks
    from doc_tools.scrub.ledger import redact
    from doc_tools.scrub.scrubber import describe_source, scrub

    value = os.environ.get(args.salt_env)
    if not value:
        print(f"error: environment variable {args.salt_env} is not set or empty",
              file=sys.stderr)
        return 2
    salt = value.encode("utf-8")
    print(f"salt from ${args.salt_env}: {redact(salt)}")

    known = frozenset()
    if args.known_mpns:
        with open(args.known_mpns, encoding="utf-8") as f:
            known = frozenset(ln.strip() for ln in f if ln.strip())

    with open(args.element_text, "rb") as f:
        raw = f.read()
    blocks = read_blocks(args.element_text)
    source = describe_source(blocks, bucket="local-element-text",
                             key=f"{args.fixture_id}.element_text", data=raw)
    allowlist = Allowlist.load(args.allowlist)
    outcome = scrub(blocks, salt=salt, salt_ref=args.salt_ref,
                    fixture_id=args.fixture_id, source=source,
                    allowlist=allowlist, known_mpns=known,
                    strict=not args.allow_unclassified)

    os.makedirs(args.out_dir, exist_ok=True)
    txt = os.path.join(args.out_dir, f"{args.fixture_id}.txt")
    led = os.path.join(args.out_dir, f"{args.fixture_id}.ledger.json")
    with open(txt, "w", encoding="utf-8", newline="\n") as f:
        f.write(outcome.text)
    with open(led, "w", encoding="utf-8", newline="\n") as f:
        f.write(outcome.ledger.model_dump_json(by_alias=True, indent=2) + "\n")

    ledger = outcome.ledger
    print(f"substitutions: {len(ledger.substitutions)}  "
          f"unclassified: {len(outcome.unclassified)}  "
          f"strict: {not args.allow_unclassified}")
    for name, check in ledger.verification.checks.items():
        print(f"  {name.value:<22} {check.result.value}")
    print(f"wrote {txt}\nwrote {led}")
    if not ledger.committable:
        print(f"NOT COMMITTABLE: {ledger.why_not_committable()}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
