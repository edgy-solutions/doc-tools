"""Generate a synthetic WI fixture shaped like the REAL corpus, for SEGMENTER work.

WHY A THIRD FIXTURE. The two existing fixtures do not have the production layout, so
a page-structure segmenter validated against them is confirmed by a document shape
that does not occur. Measured out of `mfg_corpus_report2.json` (`per_doc[].parse`),
the real documents are:

    doc        pages  elements  ops   OPERATION ####   bare ####   Title
    doc_0000    108     1823     18         94             12        74
    doc_0001    106     1604     25         74             16       109
    doc_0002    238     4295     27         70             12       317
    doc_0003    280     5410     19        100              0       307

and the four facts that matter for a segmenter are:

  1. SCALE — 100-280 pages, 18-27 operations. The old fixtures are 15 and 9 pages
     with 5 and 4 operations, two orders of magnitude away.
  2. OPERATION HEADINGS ARE `UncategorizedText`, NOT `Title`. The shape
     `OPERATION ####` occurs 70-100x per document under UncategorizedText. The old
     fixtures encode boundaries as Title elements, so a segmenter keyed on Title
     passes the mock and finds NOTHING in production. This is the mismatch that
     costs the most.
  3. THE HEADING REPEATS PER PAGE — 70-100 occurrences against 18-27 real
     operations, ~4-5x. If that holds, page->operation assignment needs no
     inference. Reproduced here so a segmenter can be tested against it.
  4. A 4-DIGIT DISTRACTOR LIVES IN PAGE FURNITURE. doc_0000's footer is
     `REVISION: ####` on all 106 pages. This is the production analogue of the
     `4500` capture the mock reproduced (DWG-4500-01 -> procedure_id 4500), so it
     is kept, not removed — the point is that the segmenter must survive it.

TWO HAZARDS DELIBERATELY REPRODUCED, because a segmenter that cannot handle them
will pass here and fail at work:

  * DUAL NOTATION. doc_0000 carries `OPERATION ####` in body text AND `OP ##`
    (TWO digits) inside Title elements, simultaneously. Here `OP NN` is the
    sequence index (01..18) while `OPERATION NNNN` is the 4-digit id — so a
    segmenter keying on "any operation-ish number" sees two disagreeing schemes.
  * CROSS-REFERENCES. Step prose says "(see Op 0200 ...)" on pages belonging to a
    different operation. Any segmenter that regexes operation numbers out of page
    TEXT mis-assigns those pages; one that keys on the standalone
    `OPERATION ####` element does not.

NOT UNIVERSAL, ALSO REPRODUCED: doc_0003 has 100 `OPERATION ####` and ZERO bare
`####`, so the SME-described standalone big-number title page is real but is not
present in every document. Here `TITLE_PAGE_EVERY` controls it — some operations
get one, some do not, so a segmenter must not REQUIRE it.

The shapes above are what `mfg_corpus_report._safe_text_shape` produces: digits ->
'#', letters -> 'a', and the structural words in `_KEEP_WORDS` (OPERATION, OP, REV,
REVISION, SHEET, NOTE, INSPECT, ...) preserved verbatim and uppercased. Element
text here is written to land on those exact shapes, so `--verify` can compare this
fixture to the real corpus numbers directly.

Content is entirely invented (a generic "Widget Mount Assembly"); only the FORM is
taken from the measurements.

Output (written next to this file):
  * synthetic_work_instruction_reallayout.json
  * synthetic_work_instruction_reallayout.groundtruth.json

Regenerate:  python tests/fixtures/manufacturing/make_synthetic_wi_reallayout.py
Verify shape: python tests/fixtures/manufacturing/make_synthetic_wi_reallayout.py --verify
"""
import collections
import json
import os
import re
import sys

# --------------------------------------------------------------------------- #
# Shape targets, taken from doc_0000 (the best-characterised real document).
# --------------------------------------------------------------------------- #
N_OPERATIONS = 18
PAGES_PER_OP = 5            # 18 x 5 = 90 operation pages; 94/18 = 5.2 measured
FRONT_MATTER_PAGES = 10     # -> ~100 pages total, vs 108 measured
TITLE_PAGE_EVERY = 2        # only SOME operations get a bare-#### title page
HEADER_EVERY = 2            # doc_0000: 66 Headers over 108 pages, NOT every page

# doc_0000 is 1823 elements over 108 pages (~17/page), and 833 of them — 46% — are
# UncategorizedText. unstructured simply fails to categorise most body text on a
# dense route sheet. That is not cosmetic: an extractor that keys on NarrativeText
# would skip nearly half the document, so a share of the STEPS here are emitted as
# UncategorizedText and still counted as steps.
UNCAT_FRAGMENTS_PER_PAGE = 5   # non-step body text that lands uncategorised
FIGURES_PER_PAGE = 2           # doc_0000: 203 Images over 108 pages

# THE HEADING DOES NOT APPEAR ON EVERY PAGE. Measured `OPERATION ####` per page:
#   doc_0000 0.87   doc_0001 0.70   doc_0002 0.29   doc_0003 0.36   doc_0005 0.00
# So in half the corpus only about a THIRD of pages declare their operation, and
# doc_0005 marks six operations without a single OPERATION line. A segmenter must
# therefore CARRY FORWARD across heading-less pages — it cannot ask each page which
# operation it belongs to. These are the page offsets within an operation that get
# the heading; the rest are silent, which is what makes the fixture discriminate.
HEADING_ON_OFFSETS = (0, 1, 3)   # 3 of 5 -> ~0.58 per page overall, mid-range
CROSSREF_ON_OFFSETS = (2, 4)     # cross-references sit on the SILENT pages

DOC_NO = "AB123-CD-EFG-001"
TITLE = "Widget Mount Assembly"
REV_FOOTER = "REVISION: 0002 (Redline 01) Widget Assembly - Ops Book"

PAGE_W, PAGE_H = 1700, 2200


def _bbox(x0, y0, x1, y1):
    return {"points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "layout_width": PAGE_W, "layout_height": PAGE_H}


class Builder:
    def __init__(self):
        self.els = []
        self._eid = 0

    def add(self, etype, text, page, y0, y1, image_path=None, html=None):
        self._eid += 1
        meta = {"page_number": page, "coordinates": _bbox(150, y0, PAGE_W - 150, y1)}
        if image_path:
            meta["image_path"] = image_path
        if html:
            meta["text_as_html"] = html
        self.els.append({"type": etype, "text": text,
                         "element_id": f"el{self._eid:05d}", "metadata": meta})


# --------------------------------------------------------------------------- #
# Invented content pools. Steps carry standards / parts / tooling / consumables
# so the deterministic extractors have something to find, exactly as the old
# fixtures do.
# --------------------------------------------------------------------------- #
STEP_POOL = [
    "Obtain the Bracket (PN-{pn}) and verify the part marking is legible.",
    "Clean the mating surfaces with isopropyl alcohol and lint-free wipes per STD-{std}.",
    "Install four (4) screws (PN-{pn}) and torque to 6.0 in-lbs using TOOL-TQ-05.",
    "Apply Adhesive Grade A (ADH-100-A) to the gasket channel per STD-{std}.",
    "Verify the EMI gasket (PN-{pn}) is fully seated with no gaps exceeding 0.010 in.",
    "Record the measured gap in SYS-TRACK before proceeding to the next operation.",
    "Check the Bracket for dents, cuts and scratches (see Op 0200 for inspection criteria).",
    "Install the Housing (PN-{pn}) onto the fixture FIX-{fix} and secure hand-tight.",
    "Connect the assembly to the functional test station per STD-{std}.",
    "Inspect workmanship per STD-{std}. When in doubt, contact the Project Engineer.",
]
NOTE_POOL = [
    "CAUTION — ESD SENSITIVE HARDWARE",
    "NOTE: Consult the Project Engineer before deviating from this sequence.",
    "WARNING — Do not apply power until the continuity check is complete.",
]
LIST_POOL = [
    "Torque wrench, calibrated within 12 months",
    "Lint-free wipes, Class 100",
    "Isopropyl alcohol, 99% (A/R)",
]
# Body text unstructured fails to categorise — continuation lines, measurements,
# callout fragments. Deliberately NOT prose-shaped: this is what makes up 46% of a
# real document and it is the half a NarrativeText-only extractor never sees.
UNCAT_POOL = [
    "0.060 in. max",
    "(01) 123-456-789",
    "Ref: STD-{std}",
    "A/R",
    "Zone A",
    "PN-{pn} (4 places)",
    "SHEET a of b",
]
PARTS_HTML = (
    "<table><thead><tr><th>PART NUMBER</th><th>DESCRIPTION</th><th>QTY</th></tr></thead>"
    "<tbody><tr><td>PN-1001</td><td>Bracket, Machined</td><td>1</td></tr>"
    "<tr><td>PN-1002</td><td>EMI Gasket</td><td>4</td></tr>"
    "<tr><td>PN-1005</td><td>Housing</td><td>1</td></tr></tbody></table>"
)


def op_id(i):
    """4-digit operation id: 0010, 0020, ... — the scheme the real corpus uses."""
    return f"{(i + 1) * 10:04d}"


def build():
    b = Builder()
    page = 0
    steps = 0
    figures = []
    operations = []
    page_to_op = {}          # ground truth for a SEGMENTER, not just for counts

    # ---- front matter: no operation owns these pages ---------------------- #
    for i in range(FRONT_MATTER_PAGES):
        page += 1
        if page % HEADER_EVERY == 0:
            b.add("Header", f"{TITLE} {DOC_NO}", page, 90, 130)
        b.add("Title", f"{TITLE} {DOC_NO} SHEET A: FRONT MATTER", page, 360, 420)
        b.add("NarrativeText", NOTE_POOL[i % len(NOTE_POOL)], page, 470, 530)
        if i == 2:
            b.add("Table", "PART NUMBER DESCRIPTION QTY PN-1001 Bracket 1 "
                           "PN-1002 EMI Gasket 4 PN-1005 Housing 1",
                  page, 600, 800, html=PARTS_HTML)
        for k in range(2):
            b.add("UncategorizedText",
                  f"({k + 1:02d}) 123-456-789", page, 850 + k * 70, 900 + k * 70)
        # ROUTE-SHEET INDEX. Operation numbers listed in FRONT MATTER, before any
        # operation begins — a boundary distractor a segmenter must not fall for.
        # These pages belong to no operation (page_to_operation is None for them).
        if i in (4, 5):
            for k in range(4):
                b.add("UncategorizedText", op_id((i - 4) * 4 + k), page,
                      1000 + k * 70, 1050 + k * 70)
        b.add("Footer", f"Front Matter - Page {page}", page, 2060, 2100)
        b.add("Footer", REV_FOOTER, page, 2110, 2150)
        page_to_op[page] = None

    # ---- the operations --------------------------------------------------- #
    for i in range(N_OPERATIONS):
        oid = op_id(i)
        operations.append(oid)

        # Some operations open with a standalone big-number TITLE PAGE (bare ####).
        # Deliberately NOT every operation: doc_0003 has zero of these.
        if i % TITLE_PAGE_EVERY == 0:
            page += 1
            b.add("UncategorizedText", oid, page, 900, 1100)      # -> shape '####'
            b.add("UncategorizedText", f"OPERATION {oid}", page, 1150, 1210)
            b.add("Footer", REV_FOOTER, page, 2110, 2150)
            page_to_op[page] = oid

        for p in range(PAGES_PER_OP):
            page += 1
            page_to_op[page] = oid
            if page % HEADER_EVERY == 0:
                b.add("Header", f"{TITLE} {DOC_NO} OP {i + 1:02d}", page, 90, 130)

            # THE BOUNDARY SIGNAL, as UncategorizedText — but only on SOME pages.
            # A segmenter has to carry it forward across the silent ones.
            if p in HEADING_ON_OFFSETS:
                b.add("UncategorizedText", f"OPERATION {oid}", page, 250, 310)

            # The competing notation: OP ## (two digits) inside a Title.
            b.add("Title", f"{TITLE} {DOC_NO} OP {i + 1:02d} SHEET A: INSPECT", page, 360, 420)

            y = 470
            # STEPS. Every other one is emitted as UncategorizedText, because that
            # is what unstructured does to nearly half a real route sheet — and a
            # step is still a step whatever unstructured called it.
            for s in range(4):
                # A cross-reference to ANOTHER operation, placed on a page that does
                # NOT declare its own. A segmenter that scrapes operation numbers out
                # of page text takes the cross-referenced id and mis-assigns the page;
                # one that only accepts a standalone OPERATION element does not.
                if p in CROSSREF_ON_OFFSETS and s == 0:
                    other = op_id((i + 7) % N_OPERATIONS)
                    txt = (f"Check the Bracket for dents, cuts and scratches "
                           f"(see Operation {other} for inspection criteria).")
                else:
                    txt = STEP_POOL[(i * 4 + p + s) % len(STEP_POOL)].format(
                        pn=1001 + ((i + s) % 12), std=1500 + ((i + p) % 8) * 50,
                        fix=100 + (i % 9))
                b.add("NarrativeText" if s % 2 == 0 else "UncategorizedText",
                      txt, page, y, y + 60)
                steps += 1
                y += 90

            # Uncategorised NON-step body text: the other half of the 46%.
            for k in range(UNCAT_FRAGMENTS_PER_PAGE):
                frag = UNCAT_POOL[(page + k) % len(UNCAT_POOL)].format(
                    pn=1001 + (k % 12), std=1500 + (k % 8) * 50)
                b.add("UncategorizedText", frag, page, y, y + 50)
                y += 60

            for _ in range(FIGURES_PER_PAGE):
                fig = f"figure-{page}-{len(figures) + 1}.jpg"
                b.add("Image", f"figure for operation {oid}", page, y, y + 150,
                      image_path=fig)
                figures.append(fig)
                y += 170
            if p % 3 == 0:
                b.add("FigureCaption", f"FIGURE {len(figures)}", page, y, y + 50)
                y += 60

            if p == 1:
                for li in LIST_POOL:
                    b.add("ListItem", li, page, y, y + 50)
                    y += 60

            # Footer furniture. Deliberately does NOT name the operation: doc_0000's
            # only heading-candidate footer shape is the REVISION line, and inventing
            # a second operation-id source would be a hazard the corpus does not have.
            b.add("Footer", f"Ops Book - Page {page}", page, 2060, 2100)
            b.add("Footer", REV_FOOTER, page, 2110, 2150)

    gt = {
        "operations": operations,
        "n_operations": len(operations),
        "n_steps": steps,
        "n_figures": len(figures),
        "figure_files": figures,
        "n_pages": page,
        # For SEGMENTER scoring: which operation owns each page (None = front
        # matter). This is the thing the old fixtures cannot score at all.
        "page_to_operation": {str(k): v for k, v in page_to_op.items()},
        "layout_notes": {
            "boundary_signal": "UncategorizedText whose text is exactly 'OPERATION <4-digit>'",
            "repeated_per_page": True,
            "competing_notation": "Title elements carry 'OP <2-digit>' (sequence index, NOT the id)",
            "furniture_distractor": "every page footer contains 'REVISION: 0002'",
            "title_pages": f"only every {TITLE_PAGE_EVERY}th operation has a bare-#### title page",
            "cross_references": "step prose cites 'see Op 0200' from other operations' pages",
        },
    }
    return b.els, gt


# --------------------------------------------------------------------------- #
# Verification against the real corpus numbers — the point of the fixture is that
# it MATCHES, so the fixture reports its own shape in the report's own vocabulary.
# --------------------------------------------------------------------------- #
_KEEP_WORDS = {
    "OPERATION", "OP", "STEP", "TASK", "SECTION", "FIGURE", "FIG", "TABLE",
    "NOTE", "WARNING", "CAUTION", "PAGE", "REV", "REVISION", "SHEET", "ITEM",
    "PROCEDURE", "FINAL", "INSPECT", "INSPECTION", "ASSY", "ASSEMBLY",
}


def _safe_text_shape(text, cap: int = 56) -> str:
    """Copy of mfg_corpus_report._safe_text_shape, so shapes are comparable."""
    out = []
    for tok in re.findall(r"\S+|\s+", (text or "").strip()[:cap]):
        if tok.isspace():
            out.append(" ")
            continue
        bare = re.sub(r"[^A-Za-z]", "", tok).upper()
        if bare in _KEEP_WORDS:
            out.append(re.sub(r"\d", "#", tok).upper())
        else:
            out.append(re.sub(r"[A-Za-z]", "a", re.sub(r"\d", "#", tok)))
    return "".join(out)


def verify(els, gt):
    types = collections.Counter(e["type"] for e in els)
    shapes = collections.defaultdict(collections.Counter)
    for e in els:
        t = (e.get("text") or "").strip()
        if t and len(t) <= 80 and re.search(r"(?i)\b(op|operation)\b|\b\d{3,4}\b", t):
            shapes[e["type"]][_safe_text_shape(t)] += 1
    u = shapes["UncategorizedText"]
    print("=== THIS FIXTURE vs the real corpus (doc_0000 / doc_0001) ===")
    print(f"{'metric':28s} {'fixture':>9} {'doc_0000':>9} {'doc_0001':>9}")
    rows = [
        ("pages", gt["n_pages"], 108, 106),
        ("elements", len(els), 1823, 1604),
        ("operations", gt["n_operations"], 18, 25),
        ("'OPERATION ####' (Uncat)", u.get("OPERATION ####", 0), 94, 74),
        ("bare '####' (Uncat)", u.get("####", 0), 12, 16),
        ("Title", types.get("Title", 0), 74, 109),
        ("UncategorizedText", types.get("UncategorizedText", 0), 833, 658),
        ("NarrativeText", types.get("NarrativeText", 0), 375, 281),
        ("Footer", types.get("Footer", 0), 212, 215),
        ("Header", types.get("Header", 0), 66, 75),
        ("Image", types.get("Image", 0), 203, 162),
        ("ListItem", types.get("ListItem", 0), 45, 56),
    ]
    for name, got, a, bb in rows:
        print(f"{name:28s} {got:>9} {a:>9} {bb:>9}")
    print("\nUncategorizedText shapes produced:")
    for s, c in u.most_common(6):
        print(f"   {c:>4}  {s!r}")
    print("\nTitle shapes produced:")
    for s, c in shapes["Title"].most_common(3):
        print(f"   {c:>4}  {s!r}")
    print("\nFooter shapes produced:")
    for s, c in shapes["Footer"].most_common(3):
        print(f"   {c:>4}  {s!r}")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    els, gt = build()
    if "--verify" in sys.argv:
        verify(els, gt)
        sys.exit(0)
    with open(os.path.join(here, "synthetic_work_instruction_reallayout.json"),
              "w", encoding="utf-8") as f:
        json.dump(els, f, indent=2)
    with open(os.path.join(here, "synthetic_work_instruction_reallayout.groundtruth.json"),
              "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2)
    print(f"Wrote {len(els)} elements across {gt['n_pages']} pages.")
    print(f"Ground truth: {gt['n_operations']} operations, {gt['n_steps']} steps, "
          f"{gt['n_figures']} figures.")
    verify(els, gt)
