"""Generate a synthetic manufacturing Work Instruction fixture.

Purpose: reproduce the manufacturing under-extraction issue (steps and figures
dropped by the LLM) on a document that captures the *form* of a real aerospace
route-sheet WI — WITHOUT any real/proprietary content. Everything here is
invented (a generic "Widget Mount Assembly").

Form features it reproduces (the ones that stress the extractor):
  * Repeated per-page HEADER furniture (a proprietary marking block) and a
    FOOTER (section name + "Page N"). No page-delimiter is emitted into the
    assembled text, so the model must infer page boundaries from the repeated
    furniture — exactly the real failure mode.
  * Multiple 4-digit OPERATIONS (procedures) whose steps are prose/bullets with
    no explicit step_id.
  * Inline [FIGURE: <file>] placeholders (unstructured Image elements) plus a few
    prose "Figure N" callouts.
  * Tables (parts list, route sheet, revision history) carrying text_as_html.
  * Standards (STD-####), internal part numbers (PN-####), consumables/slang
    (Loctite, isopropyl alcohol, epoxy), tooling (FIX-/TOOL-).

Output (written next to this file):
  * synthetic_work_instruction.json            — list[element dict], text.json shape
  * synthetic_work_instruction.groundtruth.json — expected counts for scoring

The element dicts mirror unstructured's `element.to_dict()`:
  {type, text, element_id, metadata:{page_number, coordinates:{points,
   layout_width, layout_height}, image_path?, text_as_html?}}

Regenerate:  python tests/fixtures/manufacturing/make_synthetic_wi.py
"""
import json
import os

# --- page furniture (repeated every page, like the real doc) --------------- #
DOC_NO = "DWG-4500-01"
TITLE = "Widget Mount Assembly"
REV = "Revision: 0002 (Redline 01)"
HEADER_LINES = [
    "PROPRIETARY — CONTROLLED DISTRIBUTION — See Distribution Statement",
    "ACME WIDGET CORP CONFIDENTIAL",
    DOC_NO,
    TITLE,
    REV,
]

PAGE_W, PAGE_H = 1700, 2200  # ~US-Letter at 200 dpi (unstructured hi_res pixels)


def _bbox(x0, y0, x1, y1):
    return {"points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "layout_width": PAGE_W, "layout_height": PAGE_H}


class Builder:
    def __init__(self):
        self.els = []
        self._eid = 0

    def _add(self, etype, text, page, y0, y1, image_path=None, html=None):
        self._eid += 1
        meta = {"page_number": page, "coordinates": _bbox(150, y0, PAGE_W - 150, y1)}
        if image_path:
            meta["image_path"] = image_path
        if html:
            meta["text_as_html"] = html
        self.els.append({
            "type": etype, "text": text, "element_id": f"el{self._eid:04d}",
            "metadata": meta,
        })

    def header(self, page):
        # five stacked header lines near the top of the page (y 90..330)
        for i, line in enumerate(HEADER_LINES):
            self._add("Header", line, page, 90 + i * 48, 130 + i * 48)

    def footer(self, page, section):
        self._add("Footer", section, page, 2060, 2100)
        self._add("Footer", f"Page {page}", page, 2110, 2150)

    def title(self, text, page, y=360):
        self._add("Title", text, page, y, y + 60)

    def body(self, text, page, y, etype="NarrativeText", image_path=None, html=None):
        self._add(etype, text, page, y, y + 60, image_path=image_path, html=html)


# --------------------------------------------------------------------------- #
# Document content (invented). Each "page" is (section, [blocks]).
# A block is (kind, text, extra) where kind drives the element type and whether
# it counts as a ground-truth step / figure.
#   kind: "title" | "step" | "note" | "listitem" | "figure" | "table"
# --------------------------------------------------------------------------- #
S = "step"; N = "note"; T = "title"; L = "listitem"; F = "figure"; TB = "table"

PARTS_HTML = (
    "<table><thead><tr><th>PART NUMBER</th><th>DESCRIPTION</th><th>QTY</th>"
    "<th>FIND NO</th></tr></thead><tbody>"
    "<tr><td>PN-1001</td><td>Bracket, Machined</td><td>1</td><td>4</td></tr>"
    "<tr><td>PN-1002</td><td>EMI Gasket</td><td>4</td><td>5</td></tr>"
    "<tr><td>PN-1004</td><td>Network Assembly</td><td>1</td><td>7</td></tr>"
    "<tr><td>PN-1005</td><td>Housing</td><td>1</td><td>8</td></tr>"
    "<tr><td>PN-1006</td><td>Washer</td><td>4</td><td>9</td></tr>"
    "<tr><td>PN-1007</td><td>Setscrew .250</td><td>4</td><td>10</td></tr>"
    "<tr><td>PN-1008</td><td>Screw</td><td>22</td><td>11</td></tr>"
    "<tr><td>PN-1009</td><td>Screw</td><td>4</td><td>13</td></tr>"
    "<tr><td>PN-1011</td><td>Bullet Connector</td><td>3</td><td>15</td></tr>"
    "<tr><td>PN-1012</td><td>Skin</td><td>1</td><td>16</td></tr>"
    "<tr><td>ADH-100-A</td><td>Adhesive, Grade A</td><td>A/R</td><td>17</td></tr>"
    "<tr><td>ADH-100-B</td><td>Adhesive, Grade B</td><td>A/R</td><td>18</td></tr>"
    "</tbody></table>"
)
ROUTE_HTML = (
    "<table><tbody>"
    "<tr><td>0010</td><td>Kitting Instructions</td></tr>"
    "<tr><td>0050</td><td>Bracket Sub-Assembly</td></tr>"
    "<tr><td>0100</td><td>Final Integration</td></tr>"
    "<tr><td>0150</td><td>Functional Test</td></tr>"
    "<tr><td>0200</td><td>Adjustment and Final Inspection</td></tr>"
    "</tbody></table>"
)
REV_HTML = (
    "<table><thead><tr><th>REV</th><th>AUTHORITY</th><th>DESCRIPTION</th>"
    "<th>DATE</th></tr></thead><tbody>"
    "<tr><td>2</td><td>ECR-40021</td><td>Added kitting operation 0010; "
    "converted to new template</td><td>01/01/24</td></tr></tbody></table>"
)

PAGES = [
    ("Route Sheet", [
        (N, "CAUTION — ESD SENSITIVE HARDWARE", None),
        (F, "Figure: assembled product overview", "figure-1-1.jpg"),
        (N, "Primary: Alex Vance – Engineer – 555-010-1111", None),
        (N, "Alternate: Taylor Smith – Engineer – 555-010-2222", None),
        (N, "Security: This hardware is Unclassified at all operations.", None),
        (TB, "OPERATION NUMBER OPERATION DESCRIPTION 0010 Kitting 0050 Bracket "
            "Sub-Assembly 0100 Final Integration 0150 Functional Test 0200 "
            "Adjustment and Final Inspection", ROUTE_HTML),
    ]),
    ("Configuration / Revision History", [
        (N, "Configuration Information: Over-build / under-build statement.", None),
        (TB, "REV AUTHORITY DESCRIPTION DATE 2 ECR-40021 Added kitting operation "
            "0010; converted to new template 01/01/24", REV_HTML),
        (N, "REVISION 0002.01", None),
    ]),
    ("Assembly Parts List", [
        (N, "Parts List Notes: A/R denotes as-required consumables.", None),
        (TB, "PART NUMBER DESCRIPTION QTY FIND NO PN-1001 Bracket 1 4 PN-1002 EMI "
            "Gasket 4 5 PN-1004 Network Assembly 1 7 PN-1005 Housing 1 8 PN-1006 "
            "Washer 4 9 PN-1007 Setscrew .250 4 10 PN-1008 Screw 22 11 PN-1009 "
            "Screw 4 13 PN-1011 Bullet Connector 3 15 PN-1012 Skin 1 16 ADH-100-A "
            "Adhesive Grade A A/R 17 ADH-100-B Adhesive Grade B A/R 18", PARTS_HTML),
    ]),
    ("General Instructions", [
        (T, "GENERAL NOTES", None),
        (N, "Security: This hardware is Unclassified at all operations.", None),
        (N, "Foreign Object Debris (FOD): If FOD is detected, notify the "
            "responsible inspector and complete form 99999-XYZ per STD-1200.", None),
        (N, "General process instruction requirements: STD-1000 STD-1100 STD-1200", None),
    ]),
    ("General Instructions", [
        (T, "GENERAL INSTRUCTIONS (HANDLING AND COMMON TOOLING)", None),
        (N, "The following shall be followed at all times by all personnel:", None),
        (L, "Finger cots or gloves shall be worn when handling hardware.", None),
        (L, "All screws shall be cleaned and primed before installation.", None),
        (L, "All tools and gauges shall be clean and calibrated.", None),
        (L, "Record date and time in the format MM/DD/YY HH:MM.", None),
    ]),
    # ---- Operation 0010 -------------------------------------------------- #
    ("Operation 0010", [
        (T, "Operation 0010 — Kitting Instructions", None),
        (S, "Obtain one clean ESD kitting tray for the Widget Mount Assembly "
            "(DWG-4500-01) per STD-1000.", None),
        (S, "Place a layer of anti-static foam into the kitting tray.", None),
        (S, "Verify the tray is free of foreign object debris (FOD) per STD-1200.", None),
        (S, "Insert the parts listed in the Assembly Parts List into the tray.", None),
    ]),
    ("Operation 0010", [
        (S, "Create a license-plate label for each kitted assembly per STD-1300, "
            "containing the assembly part number as a 2D barcode, the production "
            "order number, and the serial number (see Figure 1).", None),
        (F, "Figure 1: completed kit label example", "figure-2-2.jpg"),
        (S, "Attach the license plate to the tray and deliver the completed kit "
            "to the assembly area.", None),
    ]),
    # ---- Operation 0050 -------------------------------------------------- #
    ("Operation 0050", [
        (T, "Operation 0050 — Bracket Sub-Assembly", None),
        (S, "Obtain the Bracket (PN-1001). Inspect for dents, cuts, and "
            "scratches. If damaged, contact supervision.", None),
        (S, "If required, clean the Bracket with isopropyl alcohol per STD-1400. "
            "Do not immerse. Blow dry.", None),
        (S, "Clean (do not prime) four (4) setscrews (PN-1007). Install the four "
            "setscrews into the bracket cavities using a 2.5 mm hex key until "
            "snug, then back them out five (5) full turns.", None),
    ]),
    ("Operation 0050", [
        (S, "Place four (4) adhesive-backed EMI gaskets (PN-1002) onto the "
            "bracket flanges as shown; center each gasket over the opening. "
            "Alignment fixture FIX-2200 may be used.", None),
        (F, "gasket placement detail", "figure-3-3.jpg"),
        (S, "Clean and apply threadlocker (Loctite 242) to twenty-two (22) "
            "screws (PN-1008) per STD-1500 using Adhesive Grade A (ADH-100-A) or "
            "Grade B (ADH-100-B). Record cure time in operator comments.", None),
    ]),
    ("Operation 0050", [
        (S, "Place the Network Assembly (PN-1004) onto the skin (PN-1012). Verify "
            "orientation by aligning the screw holes.", None),
        (F, "network assembly orientation", "figure-4-4.jpg"),
        (S, "Install the Network Assembly to the skin using twenty-two (22) "
            "screws. Torque screws to 4.0 in-lbs using calibrated torque wrench "
            "TOOL-TQ-05.", None),
        (F, "torque sequence", "figure-4-5.jpg"),
    ]),
    # ---- Operation 0100 -------------------------------------------------- #
    ("Operation 0100", [
        (T, "Operation 0100 — Final Integration", None),
        (S, "Install three (3) bullet connectors (PN-1011) to the Housing "
            "(PN-1005) using tool TOOL-INS-01 or equivalent.", None),
        (S, "Loosely attach the two brackets to the Housing using four (4) "
            "screws (PN-1009) and four (4) washers (PN-1006). Do not tighten at "
            "this time.", None),
        (F, "bracket attachment", "figure-5-6.jpg"),
    ]),
    ("Operation 0100", [
        (S, "Remove the backing from two (2) gaskets. Align and install the two "
            "gaskets to the Network Assembly, adhesive side toward the assembly.", None),
        (S, "Install the Housing to the Network Assembly by aligning the three "
            "bullet connectors; press until fully engaged.", None),
        (F, "housing engagement", "figure-6-7.jpg"),
        (S, "Attach the brackets to the Network Assembly using four (4) screws "
            "and four (4) washers. Torque these four screws to 6.0 in-lbs, then "
            "torque the four previously installed screws to 6.0 in-lbs using "
            "torque wrench TOOL-TQ-05.", None),
    ]),
    # ---- Operation 0150 -------------------------------------------------- #
    ("Operation 0150", [
        (T, "Operation 0150 — Functional Test", None),
        (S, "Connect the assembly to the functional test station per STD-1600.", None),
        (F, "functional test setup", "figure-7-8.jpg"),
        (S, "Record the functional test results in SYS-TRACK.", None),
    ]),
    # ---- Operation 0200 -------------------------------------------------- #
    ("Operation 0200", [
        (T, "Operation 0200 — Adjustment and Final Inspection", None),
        (S, "Apply threadlocker to the four (4) skin setscrews per STD-1500 using "
            "Adhesive Grade C (ADH-100-C). Do not prime the screws.", None),
        (S, "Inspect the assembly for conformance to these work instructions.", None),
        (S, "Inspect workmanship per STD-1700 and STD-1750. Verify the sealing "
            "compound cure time for the tuning screws is recorded in operator "
            "comments per STD-1500.", None),
    ]),
    ("Operation 0200", [
        (S, "Inspect the skin surface finish: gouges and scratches in Zone A "
            "shall not exceed 0.060 in. When in doubt, contact the Project "
            "Engineer.", None),
        (F, "skin inspection zones", "figure-8-9.jpg"),
    ]),
]

_KIND_TO_TYPE = {S: "NarrativeText", N: "NarrativeText", T: "Title",
                 L: "ListItem", F: "Image", TB: "Table"}


def build():
    b = Builder()
    steps = 0
    figures = []
    operations = set()
    for page_idx, (section, blocks) in enumerate(PAGES, start=1):
        b.header(page_idx)
        y = 360
        for kind, text, extra in blocks:
            etype = _KIND_TO_TYPE[kind]
            if kind == F:
                b.body(text, page_idx, y, etype="Image", image_path=extra)
                figures.append(extra)
            elif kind == TB:
                b.body(text, page_idx, y, etype="Table", html=extra)
            else:
                b.body(text, page_idx, y, etype=etype)
                if kind == S:
                    steps += 1
            if kind == T and text.lower().startswith("operation"):
                # "Operation 0010 — ..." -> procedure id 0010
                operations.add(text.split()[1])
            y += 90
        b.footer(page_idx, section)

    ground_truth = {
        "operations": sorted(operations),
        "n_operations": len(operations),
        "n_steps": steps,
        "n_figures": len(figures),
        "figure_files": figures,
        "n_pages": len(PAGES),
    }
    return b.els, ground_truth


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    els, gt = build()
    with open(os.path.join(here, "synthetic_work_instruction.json"), "w", encoding="utf-8") as f:
        json.dump(els, f, indent=2)
    with open(os.path.join(here, "synthetic_work_instruction.groundtruth.json"), "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2)
    print(f"Wrote {len(els)} elements across {gt['n_pages']} pages.")
    print(f"Ground truth: {gt['n_operations']} operations, {gt['n_steps']} steps, "
          f"{gt['n_figures']} figures.")
    print(f"Operations: {gt['operations']}")
