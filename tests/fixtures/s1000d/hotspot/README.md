# The hotspot join fixture — authored, not measured

These files are **authored by this session**, not by the mock author of
`../mrad/`. The hotspot element and attribute names used here
(`hotspot`, `@applicationStructureIdent`) are **UNVERIFIED stand-ins**, taken
from the dispatch wording that specified this work (`hotspot/@applicationStructureIdent`)
— they are not confirmed against the real S1000D 4.2 IPD schema.

The real authored corpus in `../mrad/` contains **zero** `<hotspot>`
elements and **no SVG** anywhere (measured 2026-10-02, see `../mrad/README.md`
and `docs/handoff-next-session.md`). So this fixture cannot be, and is not
meant to be, evidence about real S1000D markup. What it seals is:

1. The parser's extraction LOGIC for a hotspot id on an IPD catalog item
   (`doc_tools/parsers/s1000d_rdf.py` section 8), in both supported
   containments — nested directly in the item, and under the containing
   figure's `<graphic>` joined by matching the hotspot's
   `@applicationStructureIdent` against the item's key.
2. The SVG-resolution join: that every hotspot id the parser extracts from
   the module resolves to an `id` actually present in the artwork, in ONE
   direction only (a graphic may carry hotspots no catalog item references,
   and that must NOT fail the seal).

## Files

- `ipd-hotspot-authored.xml` — one `<figure>`, `infoEntityIdent="ICN-ODMRADHS-00007"`,
  three catalog items exercising all three cases:
  - item `0001` — hotspot `HS-NESTED-01` nested directly inside the item
    (unambiguous, takes precedence).
  - item `0002` — no nested hotspot; resolved by matching the graphic's
    hotspot `applicationStructureIdent="0002"` against this item's `@item`
    (no `itemSeqNumber` element is present, same shape as `../mrad/`).
  - item `0003` — no hotspot at all, nested or joined.
  - `modelIdentCode="ODMRADHS"` is deliberately distinct from the real
    corpus's `ODMRAD` so this module can never be mistaken for one of the
    six `DMC-ODMRAD-*.xml` files, and the filename cannot match the corpus
    glob (`FIX.glob("DMC-ODMRAD-*.xml")` in `test_s1000d_walk_seal.py`) —
    if it did, every count-based control there (`refs == 5`, six modules)
    would silently change meaning.
- `graphic-hotspot-authored.svg` — hand-written, carries element `id`s
  `HS-NESTED-01` and `0002` (the two ids the parser should extract), plus one
  extra, unclaimed id `HS-UNCLAIMED-99`, to pin that the unclaimed direction
  is allowed.
- This `README.md`.

Cross-reference `../mrad/README.md` for the real corpus's provenance and its
own three standing cautions.
