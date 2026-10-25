"""Build ``ledger_example.json`` — a valid scrub ledger, built through the model.

Run it from PowerShell on this repo's venv interpreter, never a bare python:

    & .\\.venv\\Scripts\\python.exe tests\\fixtures\\scrub\\make_ledger_example.py

WHY A BUILT FIXTURE AND NOT A HAND-WRITTEN JSON FILE
----------------------------------------------------
Every ``original`` in a ledger is a real digest of a real string. A hand-written
example would carry invented digests, and then nothing in it could be checked:
``Substitution.covers()`` would fail for every candidate, and the file would
teach a reader a shape that does not round-trip. Built through
``ScrubLedger``, the example is *valid by construction* — and if a model
invariant tightens, this script fails rather than the fixture silently rotting.

EVERY VALUE HERE IS SYNTHETIC, DELIBERATELY
-------------------------------------------
The originals are invented (``SYN…``, ``ACME…``, ``Northwind Components``) and no
real document, part number, customer or site appears. Two reasons, and the second
is the one that matters:

1. The repo-wide rule: no document, value, filename or site identifier leaves.
2. **A truncated digest of a value drawn from a known catalogue is weakly
   identifying.** ``sha256:XXXXXXXX`` is 32 bits; a few hundred thousand
   catalogue MPNs can be hashed and compared. The redaction stops a reader who
   has no candidate list; it does not stop one who has the catalogue. That is an
   accepted limitation of the convention (see ``docs/contracts/scrub-ledger.md``),
   and it is a reason not to commit digests of real part numbers into an example
   that exists only to show the shape.
"""
from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "ledger_example.json")

#: The reserved draw space for this example (design §2.4 option i): a leading
#: letter triple no vendor in the corpus uses. Recorded in the ledger so a
#: collision claim is auditable rather than asserted.
RESERVED = "XQB"

#: original -> replacement. Shape-equal pairs, checked by the model.
SYNTHETIC = {
    "affected_1": ("SYN033R60J104KE19D", "XQB712T40M558BF23C"),
    "replacement_1": ("SYN155R60J104KE19D", "XQB884T40M558BF23C"),
    # Hand-written and WRONG on the first attempt: "Yqpzvbjf" is eight letters
    # against Northwind's nine, and the shape-equality validator rejected the
    # build. Left as a comment because it is the invariant working on its author.
    "customer_name": ("Northwind Components", "Yqpzvbjfs Mtudsgmxkk"),
    "customer_part": ("ACME-77-X", "KZQR-14-B"),
}


def build() -> dict:
    from doc_tools.scrub.ledger import (LEDGER_VERSION, redact, shape_of)
    from doc_tools.scrub.ledger import (Allowlisted, AllowlistRule, Check,
                                        CheckName, CheckResult, MappingPolicy,
                                        Policy, PolicyAnswer, ScrubLedger,
                                        ScrubRun, Site, SourceRef,
                                        Substitution, SubstitutionClass,
                                        Verification)

    def sub(cls, key, sites, *, redraws=0):
        original, replacement = SYNTHETIC[key]
        return Substitution(
            **{"class": cls},
            shape=shape_of(original),
            original=redact(original),
            replacement=replacement,
            occurrences=len(sites),
            sites=sites,
            reserved_space=RESERVED,
            redraws=redraws,
        )

    ledger = ScrubLedger(
        ledger_version=LEDGER_VERSION,
        fixture_id="example-pair-table",
        source=SourceRef(
            bucket="<corpus bucket>",
            key="<prefix>/EXAMPLE-PAIR-TABLE.pdf",
            sha256=redact(b"synthetic source bytes, not a real document"),
            pages=3,
            tables=2,
        ),
        scrub=ScrubRun(
            tool_version="scrubber-0.0.0-schema-only",
            run_at="2026-10-25T06:10:00Z",
            # A NAME. The salt itself never reaches a ledger.
            salt_ref="sandbox/scrub-batch-salt#example",
            allowlist_ref="registry/scrub_allowlist.yaml@<sha>",
            # One-way: policy.mapping below says one_way, and the model requires
            # the two to agree.
            mapping_ref=None,
        ),
        substitutions=[
            # The pair-table case (design §6.1): the same original in a cell AND
            # in a body paragraph, which is what a naive per-occurrence scrub
            # gets wrong and what the replacement-pair work is about.
            sub(SubstitutionClass.MPN_AFFECTED, "affected_1", [
                Site(page=2, kind="table_cell", row=4, col=0),
                Site(page=1, kind="body_text"),
            ]),
            sub(SubstitutionClass.MPN_REPLACEMENT, "replacement_1", [
                Site(page=2, kind="table_cell", row=4, col=1),
            ], redraws=1),
            # The customer column (design §6.3): the customer's NAME inside a
            # part number is why customer columns are scrubbed, not allowlisted.
            sub(SubstitutionClass.CUSTOMER_NAME, "customer_name", [
                Site(page=1, kind="body_text"),
            ]),
            sub(SubstitutionClass.CUSTOMER_PART_NUMBER, "customer_part", [
                Site(page=3, kind="table_cell", row=2, col=1),
            ]),
        ],
        allowlisted=[
            # The vocabulary under test. If any of these were substituted the
            # fixture would test nothing -- the HEMCG2-2683 defect was a
            # header-matching defect.
            Allowlisted(text="Part Number",
                        rule=AllowlistRule.HEADER_VOCABULARY, count=3),
            Allowlisted(text="Alternative Part Number",
                        rule=AllowlistRule.HEADER_VOCABULARY, count=1),
            Allowlisted(text="CUSTOMER PART NUMBER",
                        rule=AllowlistRule.HEADER_VOCABULARY, count=1),
            Allowlisted(text="Last Time Buy",
                        rule=AllowlistRule.NOTICE_TYPE_OR_STATUS, count=1),
            # The exact caption that proves a global affected-veto would decline
            # genuine EOL devices.
            Allowlisted(text="Table 4 - EOL Devices and No Replacement Parts",
                        rule=AllowlistRule.CAPTION, count=1),
            # Verbatim, every printed spelling: LTB extraction is date-semantic
            # and a shape-substituted date is not a date.
            Allowlisted(text="2024-06-06", rule=AllowlistRule.DATE, count=3),
            Allowlisted(text="06-Jun-2024", rule=AllowlistRule.DATE, count=1),
        ],
        verification=Verification(checks={
            CheckName.LEAK_TEST: Check(
                result=CheckResult.PASS,
                detail=("no substituted original appears in the scrubbed PDF's "
                        "own text layer, annotations or XMP metadata"),
                measurements={"pages_checked": 3, "hits": 0,
                              "min_page_text_retention": 0.98}),
            CheckName.SHAPE_EQUALITY: Check(
                result=CheckResult.PASS,
                detail="every replacement reduces to its declared shape",
                measurements={"substitutions": 4, "mismatches": 0}),
            CheckName.ALLOWLIST_INTEGRITY: Check(
                result=CheckResult.PASS,
                detail="each allowlisted string's count is unchanged",
                measurements={"entries": 7, "count_deltas": 0}),
            CheckName.STRUCTURE_INVARIANCE: Check(
                result=CheckResult.PASS,
                detail="page, table and per-table row/col counts unchanged",
                measurements={"pages": 3, "tables": 2,
                              "rows": [5, 3], "cols": [2, 3]}),
            CheckName.EQUIVALENCE_SEAL: Check(
                result=CheckResult.PASS,
                detail=("extractor output on source and fixture are equal after "
                        "applying the mapping"),
                measurements={"fields_compared": 14, "differences": 0}),
            CheckName.COLLISION_CHECK: Check(
                result=CheckResult.PASS,
                detail=("each replacement drawn from the reserved space and "
                        "checked against the corpus MPN set and ground truth"),
                measurements={"reserved_space": RESERVED, "redraws": 1,
                              "corpus_mpns_checked": 522}),
        }),
        policy=Policy(
            # RECORDED, NOT RULED. Rulings 1-4 of the 2026-10-22 design are
            # still open; this block is what makes that visible per fixture.
            manufacturer_name=PolicyAnswer.ALLOWLISTED,
            dates=PolicyAnswer.ALLOWLISTED,
            mapping=MappingPolicy.ONE_WAY,
            enters_scored_corpus=False,
            authority=("RECOMMENDATION ONLY -- 2026-10-22 design §5 rulings 1-4 "
                       "are unanswered as of 2026-10-25. Allowlisting the "
                       "manufacturer and the dates, a one-way scrub, and no "
                       "entry to the scored corpus are the safe answers, not "
                       "ruled ones."),
        ),
    )
    return json.loads(ledger.model_dump_json(by_alias=True))


def main() -> int:
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        current = ""
        if os.path.exists(OUT):
            with io.open(OUT, encoding="utf-8") as fh:
                current = fh.read()
        if current != text:
            print("LEDGER EXAMPLE DRIFT: regenerate with "
                  "make_ledger_example.py")
            return 1
        print("example matches")
        return 0
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
