"""Deterministic-layer gate for the manufacturing extractors (no LLM, instant).

Proves the code layer on the HARD fixture (the one where the LLM scored figures
0/11): standards recall, part-number recall, and figure->step binding — plus the
MISS PATH: each extractor must fail LOUDLY (emit a review-lane anomaly) on input
it shouldn't silently handle. An extractor suite that has only ever seen inputs it
handles is a phantom guard.

Loads doc_tools/utils/mfg_extractors.py directly by path so it runs under a bare
Python (no Dagster/BAML deps, no project venv).

Run:
  <python> scripts/mfg_deterministic_gate.py
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(ROOT, "tests", "fixtures", "manufacturing")


def _load_extractors():
    path = os.path.join(ROOT, "doc_tools", "utils", "mfg_extractors.py")
    spec = importlib.util.spec_from_file_location("mfg_extractors", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _recall(found, expected):
    fs, es = set(found), set(expected)
    hit = sorted(es & fs)
    missed = sorted(es - fs)
    extra = sorted(fs - es)
    return hit, missed, extra


def main():
    mx = _load_extractors()
    cfg = mx.load_extractor_config()   # committed defaults (no override set)
    with open(os.path.join(FIX, "synthetic_work_instruction_hard.json"), encoding="utf-8") as f:
        els = json.load(f)
    with open(os.path.join(FIX, "synthetic_work_instruction_hard.groundtruth.json"), encoding="utf-8") as f:
        gt = json.load(f)

    full_text = "\n".join(e.get("text", "") or "" for e in els)

    print("=" * 66)
    print("DETERMINISTIC-LAYER GATE  (hard fixture — LLM scored figures 0/11)")
    print("=" * 66)

    # --- standards ---------------------------------------------------------- #
    stds, std_anom = mx.extract_standards(full_text, cfg)
    hit, missed, extra = _recall(stds, gt["expected_standards"])
    print(f"\nSTANDARDS  recall {len(hit)}/{len(gt['expected_standards'])}")
    if missed:
        print(f"  MISSED : {missed}")
    if extra:
        print(f"  extra  : {extra}")
    print(f"  found  : {sorted(stds)}")

    # --- part numbers ------------------------------------------------------- #
    parts, _ = mx.extract_part_numbers(full_text, cfg)
    hit, missed, extra = _recall(parts, gt["expected_parts"])
    print(f"\nPART NUMBERS  recall {len(hit)}/{len(gt['expected_parts'])}")
    if missed:
        print(f"  MISSED : {missed}")
    if extra:
        print(f"  extra  : {extra}")

    # --- figure -> step binding -------------------------------------------- #
    binds, fig_anom = mx.bind_figures_to_steps(els, cfg)
    bound_files = sorted({b["figure"] for b in binds})
    hit, missed, extra = _recall(bound_files, gt["figure_files"])
    print(f"\nFIGURE BINDING  bound {len(hit)}/{gt['n_figures']} "
          f"(LLM baseline on this fixture: 0/{gt['n_figures']} resolvable)")
    if missed:
        print(f"  MISSED : {missed}")
    if fig_anom:
        print(f"  flagged for review: {[a['detail'] for a in fig_anom]}")
    for b in binds[:3]:
        print(f"    e.g. {b['figure']} -> [{b['direction']}] \"{b['step_snippet']}...\"")

    # --- MISS-PATH WITNESSES (must flag, never silently pass) --------------- #
    print("\n" + "-" * 66)
    print("MISS-PATH WITNESSES (each must produce a review-lane anomaly)")
    print("-" * 66)

    # 1. malformed standard: known prefix, no number
    _, nm = mx.extract_standards("Perform bonding per MIL- and clean per STD- as noted.", cfg)
    print(f"  malformed standard ('MIL-'/'STD-' no number): "
          f"{'FLAGGED' if nm else 'MISSED!'}  {[a['detail'] for a in nm]}")

    # 2. [FIGURE] on a page with no step
    orphan = [
        {"type": "Header", "text": "Cover", "element_id": "h", "metadata": {"page_number": 99}},
        {"type": "Image", "text": "", "element_id": "img",
         "metadata": {"page_number": 99, "image_path": "/x/figure-99-1.jpg"}},
    ]
    _, a2 = mx.bind_figures_to_steps(orphan, cfg)
    print(f"  figure on step-less page: "
          f"{'FLAGGED' if any(a['kind']=='figure_unbound' for a in a2) else 'MISSED!'}  "
          f"{[a['detail'] for a in a2]}")

    # 3. [FIGURE] with no resolvable filename, but a step present
    notarget = [
        {"type": "NarrativeText", "text": "Install the bracket.", "element_id": "s",
         "metadata": {"page_number": 5}},
        {"type": "Image", "text": "", "element_id": "img2",
         "metadata": {"page_number": 5}},  # no image_path
    ]
    _, a3 = mx.bind_figures_to_steps(notarget, cfg)
    print(f"  figure with no filename : "
          f"{'FLAGGED' if any(a['kind']=='figure_no_target' for a in a3) else 'MISSED!'}  "
          f"{[a['detail'] for a in a3]}")

    print()


if __name__ == "__main__":
    main()
