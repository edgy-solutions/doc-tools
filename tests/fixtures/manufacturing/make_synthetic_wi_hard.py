"""Generate a HARD synthetic Work Instruction fixture.

Same generic/invented content policy as make_synthetic_wi.py, but deliberately
reproduces the parts of a REAL route-sheet WI that make the model stumble on
figure_references (the "figures are in the text but none land in the list"
failure) — features the clean fixture lacked:

  * FIGURES ARE STRANDED from their step: each [FIGURE: file] is separated from
    the instruction that illustrates it by OCR-fragment callouts (part labels
    like "XXXXX-1 - Screws (22 pls.)", single letters, stray tokens) and often a
    page break — so no clean step "owns" the marker.
  * MESSY / WRAPPED steps with no explicit step_id, interspersed with those
    fragments.
  * LOPSIDED procedures: one big operation (~14 steps) and several tiny ones,
    like the real doc (one op with ~20 steps, the rest few).
  * The same repeated header/footer furniture (reproduces the 4500 pollution).

Ground truth counts only the real instruction steps and the real figure files.

Regenerate:  python tests/fixtures/manufacturing/make_synthetic_wi_hard.py
"""
import json
import os

from make_synthetic_wi import Builder, PAGES as _unused  # noqa: F401  (Builder + furniture)

# kinds
S = "step"; N = "note"; T = "title"; L = "listitem"; F = "figure"; FR = "frag"

_KIND_TO_TYPE = {S: "NarrativeText", N: "NarrativeText", T: "Title",
                 L: "ListItem", F: "Image", FR: "NarrativeText"}

# Each page: (section, [ (kind, text, image_or_None) ])
PAGES = [
    ("Route Sheet", [
        (N, "CAUTION - ESD SENSITIVE HARDWARE", None),
        (F, "assembled product overview", "figure-1-1.jpg"),   # cover art, no step owns it
        (N, "Primary: Alex Vance - Engineer - 555-010-1111", None),
        (N, "Alternate: Taylor Smith - Engineer - 555-010-2222", None),
    ]),
    # ---- Operation 0010 (small) ----------------------------------------- #
    ("Operation 0010", [
        (T, "Operation 0010 - Kitting Instructions", None),
        (S, "Obtain one clean ESD kitting tray for the Widget Mount Assembly "
            "(DWG-4500-01) per STD-1000 and place a layer of anti-static foam "
            "into the tray.", None),
        (S, "Make individual license plates for each assembly kitted, as shown "
            "in Figure 1, containing the assembly part number, production order "
            "number, and serial number per STD-1300.", None),
        (FR, "Serial Number", None),
        (FR, "Production Order", None),
        (F, "completed label for the assembly", "figure-2-2.jpg"),   # stranded after fragments
        (FR, "Figure 1: Completed label for the Assy Part Name", None),
    ]),
    # ---- Operation 0050 (BIG, ~14 steps, stranded figures) -------------- #
    ("Operation 0050", [
        (T, "Operation 0050 - Bracket Sub-Assembly", None),
        (F, "bracket isometric view", "figure-3-3.jpg"),             # figure BEFORE any step
        (S, "Obtain the Bracket (PN-1001). Check the Bracket for dents, cuts and "
            "scratches (see Op 0200 for inspection criteria). If damaged, "
            "contact supervision.", None),
        (FR, "XXXXX-1 - Bracket", None),
        (S, "If required, clean the Bracket with isopropyl alcohol per STD-1400. "
            "Do not immerse the unit in an alcohol bath. Blow dry and place the "
            "Bracket face down.", None),
        (S, "Clean (do not prime) four (4) tuning screws. Install the four "
            "tuning screws into the cavities using a 2.5 mm hex key until snug. "
            "Back the four screws out five (5) complete 360 degree revolutions.", None),
    ]),
    ("Operation 0050", [
        (S, "Place four (4) adhesive-backed EMI gaskets (PN-1002) onto the "
            "bracket flanges as shown. Center each gasket over the opening. "
            "Alignment fixture FIX-2200 may be used.", None),
        (FR, "Center gaskets to openings", None),
        (F, "gasket placement", "figure-4-4.jpg"),                  # stranded
        (FR, "XXXXX-1 - Gaskets (4 places)", None),
        (FR, "XXXXX-1 - Set Screws (4 pls.)", None),
        (FR, "Install until snug and then back out 5 complete turns", None),
        (S, "Clean and apply threadlocker (Loctite 242) to twenty-two (22) "
            "screws (PN-1008) per STD-1500 using ADH-100-A or ADH-100-B. Record "
            "cure time information per STD-1500 in operator comments.", None),
    ]),
    ("Operation 0050", [
        (S, "Place the Network Assembly (PN-1004) onto the skin. Verify proper "
            "orientation by aligning the screw holes as shown.", None),
        (F, "network assembly onto skin", "figure-5-5.jpg"),
        (FR, "skin", None),
        (S, "Install the Network Assembly to the skin using twenty-two (22) "
            "screws. Torque screws to 4.0 in-lbs using a TOOL-TQ-05 torque "
            "wrench.", None),
        (FR, "XXXXX-1 - Network Assy.", None),
        (F, "torque sequence detail", "figure-5-6.jpg"),            # stranded after step
        (FR, "Screws (22 pls.)", None),
        (FR, "Align screw holes", None),
    ]),
    ("Operation 0050", [
        (S, "Install three (3) bullet connectors (PN-1011) to the Housing "
            "(PN-1005) using tool TOOL-INS-01 or equivalent.", None),
        (S, "Loosely attach the two brackets to the Housing using four (4) "
            "screws (PN-1009) and four (4) washers (PN-1006). Do not tighten the "
            "screws at this time.", None),
        (FR, "XXXXX-1", None),
        (F, "housing and brackets", "figure-6-7.jpg"),
        (FR, "Screw Washer note: hardware may not look exactly like the picture", None),
        (FR, "XXXXX-1 - Screw (4 pls.)", None),
        (FR, "XXXXX-1 - Washer (4 pls.)", None),
    ]),
    ("Operation 0050", [
        (S, "Remove the backing from two (2) gaskets. Align and install the two "
            "gaskets to the Network Assembly with the adhesive side toward the "
            "assembly.", None),
        (S, "Install the Housing to the Network Assembly by aligning the three "
            "(3) bullet connectors with the mating connectors. Carefully press "
            "the Housing until the three connectors fully engage.", None),
        (F, "connector engagement", "figure-7-8.jpg"),
        (FR, "A", None),
        (S, "Attach the brackets to the Network Assembly using four (4) screws "
            "and four (4) washers. Torque these four screws first to 6.0 in-lbs "
            "using a TOOL-TQ-05 torque wrench. Torque the four previously "
            "installed screws to 6.0 in-lbs.", None),
        (FR, "XXXXX-1 Screws (4 pls.) XXXXX-1 Washers (4 pls.)", None),
        (F, "final torque detail", "figure-7-9.jpg"),               # stranded
    ]),
    # ---- Operation 0150 (tiny) ------------------------------------------ #
    ("Operation 0150", [
        (T, "Operation 0150 - Functional Test", None),
        (F, "test station connection", "figure-8-10.jpg"),          # figure before/without step
        (S, "Connect the assembly to the functional test station per STD-1600 "
            "and record the results in SYS-TRACK.", None),
    ]),
    # ---- Operation 0200 (small) ----------------------------------------- #
    ("Operation 0200", [
        (T, "Operation 0200 - Adjustment and Final Inspection", None),
        (S, "Apply threadlocker to the four (4) skin setscrews per STD-1500 "
            "using ADH-100-C. Do not prime the screws.", None),
        (S, "Inspect workmanship per STD-1700 and STD-1750. Verify the sealing "
            "compound cure time for the tuning screws is recorded in operator "
            "comments per STD-1500.", None),
        (S, "Inspect the skin surface finish per the following: gouges and "
            "scratches in Zone A shall not exceed 0.060 in. When in doubt, "
            "contact the Project Engineer.", None),
        (FR, "Zone B (2 pls.)", None),
        (FR, "Cross-hatched areas indicate Zone A", None),
        (F, "skin inspection zones", "figure-9-11.jpg"),            # stranded at end
    ]),
]


def build():
    b = Builder()
    steps = 0
    figures = []
    operations = set()
    for page_idx, (section, blocks) in enumerate(PAGES, start=1):
        b.header(page_idx)
        y = 360
        for kind, text, image in blocks:
            if kind == F:
                b.body(text, page_idx, y, etype="Image", image_path=image)
                figures.append(image)
            else:
                b.body(text, page_idx, y, etype=_KIND_TO_TYPE[kind])
                if kind == S:
                    steps += 1
            if kind == T and "operation" in text.lower():
                operations.add(text.split()[1])
            y += 90
        b.footer(page_idx, section)
    # Author-declared (NOT regex-derived, so recall measurement is non-circular).
    expected_standards = ["STD-1000", "STD-1300", "STD-1400", "STD-1500",
                          "STD-1600", "STD-1700", "STD-1750"]
    expected_parts = ["PN-1001", "PN-1002", "PN-1004", "PN-1005", "PN-1006",
                      "PN-1008", "PN-1009", "PN-1011",
                      "ADH-100-A", "ADH-100-B", "ADH-100-C"]
    # figure-1-1.jpg is cover art on a page with no step -> deliberately unbindable
    # (a miss-path witness: it must be flagged for review, not dropped or misbound).
    gt = {"operations": sorted(operations), "n_operations": len(operations),
          "n_steps": steps, "n_figures": len(figures), "figure_files": figures,
          "n_pages": len(PAGES),
          "expected_standards": expected_standards,
          "expected_parts": expected_parts,
          "unbindable_figures": ["figure-1-1.jpg"]}
    return b.els, gt


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    els, gt = build()
    with open(os.path.join(here, "synthetic_work_instruction_hard.json"), "w", encoding="utf-8") as f:
        json.dump(els, f, indent=2)
    with open(os.path.join(here, "synthetic_work_instruction_hard.groundtruth.json"), "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2)
    print(f"Wrote {len(els)} elements across {gt['n_pages']} pages.")
    print(f"Ground truth: {gt['n_operations']} operations, {gt['n_steps']} steps, "
          f"{gt['n_figures']} figures.")
    print(f"Operations: {gt['operations']}")
