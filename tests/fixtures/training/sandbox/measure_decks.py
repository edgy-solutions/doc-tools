"""Measure what python-pptx says each fixture deck holds (local, read-only).

    python measure_decks.py <fixtures_dir> <out measure.json>

One entry per deck folder: {"slide_count": N, "hidden": [slide numbers]}. This
is deck_table.py's independent side: what the deck holds, not what was written.
"""
import json
import os
import sys


def main(fx, out):
    from pptx import Presentation
    res = {}
    for slug in sorted(os.listdir(fx)):
        d = os.path.join(fx, slug)
        decks = sorted(n for n in os.listdir(d) if n.endswith(".pptx")) if os.path.isdir(d) else []
        if not decks:
            continue
        prs = Presentation(os.path.join(d, decks[0]))
        slides = list(prs.slides)
        res[slug] = {"slide_count": len(slides),
                     "hidden": [i for i, s in enumerate(slides, 1) if s._element.get("show") == "0"]}
    with open(out, "wb") as f:
        f.write((json.dumps(res, indent=2) + "\n").encode("utf-8"))
    print(f"wrote {out}: {len(res)} decks")


if __name__ == "__main__":
    main(*sys.argv[1:])
