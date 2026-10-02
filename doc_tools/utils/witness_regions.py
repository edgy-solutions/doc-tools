"""Locate the header REGIONS a vision witness should be asked about, and convert
their text-layer geometry into a crop box in the page raster's pixels.

WHY REGIONS AND NOT THE WHOLE PAGE. The second witness used to transcribe the
entire page and let `sustainment_header_trust` search the transcription for a
header value. Measured against the live host on TYC-PCN-24-210412 (2026-10-01),
that read fails in a specific, repeatable way: asked about the WHOLE page the
model answers `10-Jan-2024` for a date the page prints as `10-Jun-2024` --
twice, one-shot and multi-turn -- while the SAME model on the SAME host asked
about a CROP of the header block answers `10-Jun-2024`. Raising the page DPI
(150 -> 200) fixed two other dates on that page but never this one. So the
defect is not resolution: a whole-page transcription asks the model to hold a
page of layout in its head, and a crop asks it to read a line.

WHY THE TEXT LAYER STILL DRIVES IT, EVEN WHEN THE TEXT LAYER IS THE PROBLEM.
The witness exists precisely because a document's text layer is damaged, which
looks circular -- but the damage is to GLYPHS, not to GEOMETRY. TYC's layer
loses every `ti` ("Estimated" -> "Esmated", "TE Connectivity" ->
"TE Connecvity") while each element's coordinates stay exactly right. The layer
is therefore a trustworthy map of WHERE the blocks are and an untrustworthy
record of WHAT they say, and this module uses it for only the first.

That cuts one way that matters: a locator matching the literal string
"Estimated Dates" MISSES on the one notice the witness was built for --
confirmed against the real document, where the literal search returns no hits
and the folded search returns exactly one. Every match here goes through
`fold_ligatures`, which deletes the ligature sequences from BOTH sides, so
"Estimated Dates" and the damaged "Esmated Dates" fold to the same key and the
locator is blind to whether the drop happened.

COORDINATE SPACES -- there are three, and mixing them silently misplaces a crop:
  1. PDF points (72/inch), what pdfplumber reports. Not used here.
  2. unstructured's LAYOUT pixels, what `metadata.coordinates.points` holds and
     what `provenance.build_positioned_index` stores as `bbox`, relative to
     `layout_width`/`layout_height`. This module's input.
  3. The PAGE RASTER's pixels, `rasterize_pdf_pages`' output, whose dimensions
     the manifest records per page. This module's output.
Both 2 and 3 frame the whole page, so the conversion is one ratio --
`img_h / layout_h` -- needing no DPI and no PDF. `region_pixel_box` checks that
the two aspect ratios agree before trusting it, because a mismatch means the
rasters are not framing the same thing and the crop would be confidently wrong
rather than merely imprecise.
"""
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Longest first: a naive alternation would take "fi" out of "ffi" and leave "f".
_LIGATURES = re.compile(r"(ffi|ffl|fi|fl|ff|ti)")
# A damaged layer can also leave the dropped glyph as a NUL or other control
# byte rather than removing it -- pdfplumber reports TYC's as "Es\x00mated"
# where unstructured reports "Esmated". Stripped before folding so both
# spellings reach the same key.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def fold_ligatures(s: Optional[str]) -> str:
    """A match key that survives a text layer dropping its ligature glyphs.

    Control bytes removed, whitespace removed, lowercased, and the ligature
    sequences deleted. Applied to BOTH needle and haystack, which makes it
    idempotent with respect to the damage: "Estimated" folds to "esmaed"
    whether the layer gave us "Estimated" or the damaged "Esmated".

    Deliberately LOSSY and deliberately not offset-preserving -- this is for
    locating a labelled block, never for extracting a value or mapping a match
    back onto the original string. (That second mistake lives one module over:
    see the note on `fold_typography` in `sustainment_header_trust`.)
    """
    return _LIGATURES.sub("", re.sub(r"\s+", "", _CONTROL.sub("", s or "")).lower())


# The regions the witness is asked about, in the order they are asked. `fields`
# names the header fields each region is expected to answer: it documents the
# coverage this module owes `sustainment_header_trust` and is what a test can
# assert against, so a field silently losing its witness surfaces as a failure
# rather than as a quiet drop in corroboration. `prompt_section` is the heading
# in prompts/sustainment_read_region.md carrying that region's questions -- the
# question TEXT lives in the prompt file, not here, so it ships through the
# ordinary PROMPT_SOURCE path.
REGION_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "header_block",
        "fields": ("mfr", "doc_id", "pub_date"),
        "prompt_section": "header_block",
    },
    {
        "name": "estimated_dates",
        "fields": ("doc_level_ltb_date",),
        "prompt_section": "estimated_dates",
    },
)

# Folded keys that identify the dates block. Several spellings because the label
# varies across manufacturers; all are folded at import so a comparison never
# depends on the caller remembering to fold.
_DATES_LABELS = tuple(fold_ligatures(s) for s in (
    "Estimated Dates",
    "Estimated Date",
    "Key Dates",
    "Important Dates",
    "Last Time Buy",
    "Last Order Date",
))

# A header block cannot plausibly be most of the page. If the union of the
# elements above the first table runs past this fraction of the page, the layout
# is not what the locator assumes (no table, or a table far down the page) and
# the box is clamped to the top band instead -- a crop of nearly the whole page
# would silently reintroduce the defect this module exists to fix.
_HEADER_MAX_FRACTION = 0.45
_HEADER_FALLBACK_FRACTION = 0.33

# How far below a caption its values are allowed to sit, as a fraction of page
# height. A caption element carries the label and none of the dates, so the crop
# has to reach the rows underneath it; this bounds that reach so a caption at
# the foot of a page cannot drag in the whole of the next block.
_CAPTION_REACH_FRACTION = 0.16
# Text shorter than this (folded) is a label, not a populated block.
_CAPTION_MAX_LEN = 48


def _page_records(index: Sequence[dict], page_number: int) -> List[dict]:
    """Records on one page that carry usable geometry, in reading order."""
    return [r for r in index
            if r.get("bbox") and r.get("page_number") == page_number
            and r.get("page_height")]


def _union(boxes: Sequence[Sequence[float]]) -> Tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _is_table(rec: dict) -> bool:
    return rec.get("region") == "table" or rec.get("type") == "Table"


def locate_header_block(index: Sequence[dict], page_number: int = 1) -> Optional[dict]:
    """The title/masthead band: everything above the page's first table.

    `mfr`, `doc_id` and `pub_date` are printed in the block above the first grid
    on page 1 on every notice in this corpus. Cutting at "above the first table"
    rather than at a fixed fraction keeps the crop tight where the masthead is
    short and still contains a tall one; the clamp above catches the layouts
    where that assumption does not hold.
    """
    recs = _page_records(index, page_number)
    if not recs:
        return None
    page_h = float(recs[0]["page_height"])
    page_w = float(recs[0].get("page_width") or 0.0)
    cut = min((r["bbox"][1] for r in recs if _is_table(r)), default=None)
    if cut is not None:
        above = [r for r in recs if r["bbox"][3] <= cut + 1.0]
        if above:
            box = _union([r["bbox"] for r in above])
            if (box[3] - box[1]) / page_h <= _HEADER_MAX_FRACTION:
                return _region(box, recs[0], page_number, "header_block",
                               f"union of {len(above)} elements above the first "
                               f"table at y={cut:.0f}")
    return _region((0.0, 0.0, page_w, page_h * _HEADER_FALLBACK_FRACTION),
                   recs[0], page_number, "header_block",
                   f"top {_HEADER_FALLBACK_FRACTION:.0%} band "
                   f"(no usable table cut)")


def locate_estimated_dates(index: Sequence[dict],
                           page_number: Optional[int] = None) -> Optional[dict]:
    """The dates block, found by its LABEL through the ligature fold.

    Searches every page, because the block is not always on page 1. The label
    is frequently its OWN element, carrying no dates at all -- on TYC it is a
    61x16 pt element reading "Esmated Dates:" with the values in the elements
    below it -- so a crop of the labelled element alone would contain nothing
    worth asking about. When the match looks like a bare label, the box is
    unioned with the following elements within `_CAPTION_REACH_FRACTION` of the
    page below it, which covers both layouts: a caption above a real Table, and
    a caption above loose label/value lines.
    """
    pages = ([page_number] if page_number
             else sorted({r.get("page_number") for r in index
                          if r.get("page_number")}))
    for pg in pages:
        recs = _page_records(index, pg)
        for i, rec in enumerate(recs):
            folded = fold_ligatures(rec.get("text", ""))
            if not any(lbl and lbl in folded for lbl in _DATES_LABELS):
                continue
            # The label has to be a LABEL or a GRID, not a sentence. Notice prose
            # says things like "the estimated date of the first shipment is stated
            # in the attached schedule", which matches every one of these labels
            # while containing no dates block at all -- cropping that paragraph
            # would spend a vision call asking a sentence for two dates.
            if not (_is_table(rec) or len(folded) < _CAPTION_MAX_LEN):
                continue
            boxes = [rec["bbox"]]
            why = "labelled element"
            if len(folded) < _CAPTION_MAX_LEN:
                below, stopped_at = _rows_under_caption(recs, i)
                if below:
                    boxes.extend(r["bbox"] for r in below)
                    why = (f"bare label plus the {len(below)} element(s) under it, "
                           f"stopping at {stopped_at}")
            return _region(_union(boxes), recs[0], pg, "estimated_dates", why)
    return None


def _rows_under_caption(recs: Sequence[dict],
                        caption_i: int) -> Tuple[List[dict], str]:
    """The rows a bare label captions: walk forward until the block ends.

    The block ends at whichever comes first:
      * the next SECTION HEADING -- unstructured types it `Title`, and on the
        notice this was built against that heading ("Part Number(s) being
        Modified:") sits only 18 pt below the last dates row, close enough that
        any purely numeric gap rule generous enough to keep the rows would also
        swallow the next section;
      * `_CAPTION_REACH_FRACTION` of the page below the caption, so a caption
        with no heading after it cannot run away down the page.

    Returns the rows and a human-readable account of which limit stopped it,
    which rides on the region record as `located_by`.
    """
    caption = recs[caption_i]
    page_h = float(caption["page_height"])
    reach = caption["bbox"][3] + _CAPTION_REACH_FRACTION * page_h
    rows: List[dict] = []
    for rec in recs[caption_i + 1:]:
        if rec.get("type") == "Title":
            return rows, "the next section heading"
        if rec["bbox"][3] > reach:
            return rows, f"{_CAPTION_REACH_FRACTION:.0%} of the page below the label"
        if rec["bbox"][1] < caption["bbox"][1]:
            continue  # above the label: a different column, not this block
        rows.append(rec)
    return rows, "the end of the page"


def _region(box, ref: dict, page_number: int, name: str, why: str) -> dict:
    """One located region. `located_by` is carried so a surprising crop can be
    explained from the record alone, without re-running the locator."""
    return {
        "name": name,
        "page_number": page_number,
        "bbox": [float(box[0]), float(box[1]), float(box[2]), float(box[3])],
        "page_width": ref.get("page_width"),
        "page_height": ref.get("page_height"),
        "located_by": why,
    }


def locate_regions(index: Sequence[dict]) -> List[dict]:
    """Every region this witness can find, in REGION_SPECS order.

    A region that cannot be located is OMITTED rather than returned empty: the
    witness is corroboration, so a missing region costs the fields it would have
    answered and nothing else, exactly as a failed page used to. The caller
    reports the count, so a document whose regions all went missing is visible
    in the stats instead of looking like a witness that simply found nothing.
    """
    out: List[dict] = []
    for spec in REGION_SPECS:
        if spec["name"] == "header_block":
            found = locate_header_block(index)
        elif spec["name"] == "estimated_dates":
            found = locate_estimated_dates(index)
        else:  # pragma: no cover - REGION_SPECS is closed
            found = None
        if found:
            found["fields"] = list(spec["fields"])
            found["prompt_section"] = spec["prompt_section"]
            out.append(found)
    return out


def region_pixel_box(region: dict, img_w: int, img_h: int,
                     pad_fraction: float = 0.01) -> Optional[Tuple[int, int, int, int]]:
    """A layout-pixel region box -> a crop box in the page raster's pixels.

    Padded by `pad_fraction` of the page height (~8 pt on Letter, enough that a
    descender or a box rule is not shaved off) and clamped to the image. The pad
    is a FRACTION rather than a DPI-derived constant so this stays correct at
    whatever DPI the page was rendered at; the manifest records that DPI, but
    not needing it means one less value that can be stale.

    Returns None when the two rasters disagree about the page's shape or the
    result is degenerately small -- the failure modes that would place a
    confidently wrong crop rather than a slightly loose one.
    """
    lw, lh = region.get("page_width"), region.get("page_height")
    if not lw or not lh or not img_w or not img_h:
        return None
    ratio_h = float(img_h) / float(lh)
    ratio_w = float(img_w) / float(lw)
    if abs(ratio_w - ratio_h) > 0.02 * max(ratio_w, ratio_h):
        return None
    pad = max(4.0, pad_fraction * float(img_h))
    x0, y0, x1, y1 = (float(v) * ratio_h for v in region["bbox"])
    box = (int(max(0, round(x0 - pad))), int(max(0, round(y0 - pad))),
           int(min(img_w, round(x1 + pad))), int(min(img_h, round(y1 + pad))))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    return box


# --------------------------------------------------------------------------- #
# Prompt sections
# --------------------------------------------------------------------------- #
_SECTION_RE = re.compile(r"^##[ \t]+(\S+)[ \t]*$", re.MULTILINE)


def split_prompt_sections(markdown: str) -> Dict[str, str]:
    """`## <name>` -> that section's body, for prompts/sustainment_read_region.md.

    The per-region questions live in the prompt FILE rather than in this module
    so they ship through the ordinary prompt path -- git-committed canonical
    text, editable in Langfuse under PROMPT_SOURCE -- instead of being frozen in
    code. A `common` section, where present, is prepended to every region's text
    by `region_prompt`.
    """
    out: Dict[str, str] = {}
    marks = list(_SECTION_RE.finditer(markdown or ""))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(markdown)
        out[m.group(1)] = markdown[m.end():end].strip()
    return out


def region_prompt(markdown: str, section: str) -> str:
    """The instructions for one region: the `common` preamble plus its section.

    RAISES on a missing section rather than returning "". A vision call with no
    instructions does not fail -- it answers something, and the run looks like a
    near-pass while the witness quietly reads nothing it was asked to read. That
    failure mode has cost this lane a measurement before, so an absent section
    is an error raised up front by `validate_region_prompt`, at the same point
    `_ensure_prompts_available` checks that the files exist.
    """
    sections = split_prompt_sections(markdown)
    body = sections.get(section)
    if not body:
        raise ValueError(
            f"prompts/sustainment_read_region.md has no '## {section}' section "
            f"(found: {sorted(sections) or 'none'}); the region witness would be "
            f"called with no instructions"
        )
    common = sections.get("common", "")
    return f"{common}\n\n{body}".strip() if common else body


def validate_region_prompt(markdown: str) -> None:
    """Every REGION_SPECS section resolves. Called once, up front."""
    for spec in REGION_SPECS:
        region_prompt(markdown, spec["prompt_section"])


# --------------------------------------------------------------------------- #
# READING THE ANSWERS BACK -- the half that makes the questions worth asking.
#
# A region read that only CORROBORATES cannot fix a wrong value, and measured on
# TYC-PCN-24-210412 (2026-10-01, three fires) every header field this witness is
# asked about came back CORRECT while the shipped header stayed wrong, because
# nothing could write what the witness read:
#
#   field                raw header (text layer)   region witness   page prints
#   mfr                  TE Connecvity             TE Connectivity  TE Connectivity
#   pub_date             2024-06-10 (print stamp)  07-JUN-24        07-JUN-24
#   doc_level_ltb_date   2024-06-06 then REFUSED   06-JUN-2024      06-JUN-2024
#
# The first two were not even refused: a damaged text layer prints `TE Connecvity`
# verbatim, so the value is "supported by the document" and passes the filter
# intact, and `2024-06-10` really is printed on the page -- as the portal's print
# stamp. A filter cannot reach either case. So the witness becomes a SUPPLIER for
# the fields it was asked about, on a document whose text layer is measured
# degraded, and `sustainment_header_trust.supply_header_from_regions` writes it.
#
# WHAT GUARDS THE SUPPLY. Vision substitutes digits, which is exactly why this was
# not simply trusted: writing a wrong date is worse than keeping an unverified one.
# Two guards, both built into the QUESTIONS rather than bolted on afterwards:
#
#   1. THE DISTRACTOR. `Current Date:` is asked separately from `Notice Date:`
#      precisely because the measured failure is conflating the two. If the model
#      answers them with the SAME date it has collapsed the distinction, and no
#      pub_date is supplied.
#   2. THE REDUNDANT LINE. `All Dates:` re-reads the dates block as explicit
#      `label = date` pairs, so the date the model paired with "last order" can be
#      checked against the date it reported for that question. A DISAGREEMENT
#      blocks the supply; silence does not -- absence from a witness is not
#      evidence, and a crop with one date may legitimately produce no pair.
# --------------------------------------------------------------------------- #

# `Label: value`, tolerant of the bullet and backtick decoration a model adds back
# even when asked for plain text. The label is bounded to letters, spaces and
# brackets so a date's own colon-free text cannot be mistaken for a new label.
_ANSWER_LINE_RE = re.compile(r"^[\s\-*\u2022]*`?\s*([A-Za-z][A-Za-z ()/]{0,40}?)\s*`?\s*:\s*(.+?)\s*$")

# Every way the prompt's own `not printed` comes back, folded. A model asked for a
# value it cannot see says so in a handful of forms; all of them mean "no answer",
# and treating any of them as a VALUE would write the literal string into a header.
_NO_ANSWER = frozenset((
    "notprinted", "none", "na", "n/a", "nil", "notavailable", "notapplicable",
    "absent", "unknown", "notshown", "nodate", "", "-", "--",
))

# label (normalized) -> (header field, kind). `kind` selects how the answer is
# turned into a value: "date" normalizes to ISO, "text" is taken verbatim.
# `currentdate` is deliberately absent: it is asked ONLY to be discarded.
REGION_FIELD_ANSWERS: Dict[str, Tuple[Tuple[str, str, str], ...]] = {
    "header_block": (
        ("manufacturer", "mfr", "text"),
        ("documentnumber", "doc_id", "text"),
        ("noticedate", "pub_date", "date"),
    ),
    "estimated_dates": (
        ("lastorderdate", "doc_level_ltb_date", "date"),
    ),
}

_LABEL_KEY_RE = re.compile(r"[^a-z0-9]+")
# Labels in the `All Dates:` line that denote the last ORDER date, for the
# redundancy check. Substring match after normalization, because a real notice
# prints "Last Order Date (Obsolete Parts Only)".
_LAST_ORDER_KEYS = ("lastorder", "lasttimebuy", "lastbuy", "ltb")


def _label_key(s: str) -> str:
    return _LABEL_KEY_RE.sub("", (s or "").lower())


def parse_region_answer(text: Optional[str]) -> Dict[str, str]:
    """A region's answer text -> {normalized label: verbatim value}.

    Values are kept EXACTLY as the model printed them, because a supplied header
    value needs a citation that is verbatim on the page -- normalizing here would
    manufacture a source string that the page does not contain. Lines that are not
    `Label: value` are dropped rather than guessed at.
    """
    out: Dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _ANSWER_LINE_RE.match(line)
        if not m:
            continue
        key, value = _label_key(m.group(1)), m.group(2).strip().strip("`").strip()
        if not key or key in out:
            continue  # first answer wins; a repeated label is the model rambling
        out[key] = value
    return out


# An answer that is ALREADY an ISO date, matched anchored. See `_iso_date` for why
# this cannot go through the shared date finder.
_ISO_ANSWER_RE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")


def _iso_date(value: Optional[str]) -> Optional[str]:
    """`07-JUN-24` -> `2024-06-07`, or None when the text names no single date.

    Two paths, and the split is not tidiness. Named-month typographies go through
    `ltb_candidates._find_dates`, borrowed rather than reimplemented because it
    already handles every such form measured in this corpus including the 2-digit
    year TYC prints, and a SECOND date parser is how two call sites come to
    disagree about what a date means.

    But that function cannot parse an ALL-NUMERIC date at all: its
    `_try_date` routes the month through `_month_num`, a NAME lookup, so `2024-06-07`
    and `06/07/2024` both return nothing from it even though its own
    `_ISO_DASH_RE`/`_MDY_SLASH_RE` match them. That is a latent defect in
    `ltb_candidates` -- a notice printing "last order date: 06/07/2024" yields no
    candidate -- and it is NOT fixed from here: changing it would change LTB
    candidate generation across the whole corpus, which is a measured change, not a
    drive-by. So the ISO form, which is unambiguous, is matched here instead.

    An ambiguous numeric form (`06/07/2024`) deliberately returns None rather than
    picking a reading. This module's whole job is to WRITE a value, and the repo's
    standing rule (see `_date_components_consistent`) is that guessing D/M against
    M/D trades a fabrication risk for a silent off-by-months one. None means the
    field is not supplied, which is the safe outcome.

    Requires exactly one date in the answer -- two dates in a single-date answer is
    a mispairing of the kind these two-column grids produce, not a value.
    """
    text = (value or "").strip()
    m = _ISO_ANSWER_RE.match(text)
    if m:
        try:
            from datetime import date as _date
            return _date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    from doc_tools.utils.ltb_candidates import _find_dates
    found = _find_dates(text)
    isos = {iso for _, _, iso in found}
    return found[0][2] if len(isos) == 1 else None


def _all_dates_pairs(line: Optional[str]) -> List[Tuple[str, str]]:
    """The `All Dates:` line -> [(normalized label, ISO date)] for each parseable pair.

    The prompt asks for `label = date` and the live host answers with `label: date`
    -- measured on TYC, where every pair came back colon-separated. Accepting only
    the form that was ASKED for made this guard return no pairs at all on the real
    data, which is the worst possible failure for a cross-check: silence does not
    block a supply, so the guard was inert while looking present. Both separators
    are taken, whichever appears first, because the date itself contains neither.
    """
    pairs: List[Tuple[str, str]] = []
    for chunk in (line or "").split("|"):
        cuts = [i for i in (chunk.find("="), chunk.find(":")) if i >= 0]
        if not cuts:
            continue
        cut = min(cuts)
        label, date_text = chunk[:cut], chunk[cut + 1:]
        iso = _iso_date(date_text)
        if iso and label.strip():
            pairs.append((_label_key(label), iso))
    return pairs


def header_values_from_regions(witness: Sequence[dict]) -> Tuple[
        Dict[str, Tuple[str, str]], List[str]]:
    """What the region witness is willing to ASSERT: {field: (value, source)}.

    `source` is the model's verbatim answer, which is what the page prints, so the
    supplied value arrives at `refuse_unsourced_header_values` with a citation that
    the witness itself contains -- the ordinary corroboration path then re-checks it
    instead of this function being trusted on its own say-so.

    The second return value is the notes: every answer this function DECLINED to
    supply and why. They are returned rather than logged because a header field
    that had a correct witness and was still not written is precisely what a human
    reading the narrative needs to see.
    """
    answers: Dict[str, Dict[str, str]] = {}
    for rec in witness or ():
        name = str(rec.get("element_id") or "").split("_")[-1]
        for spec in REGION_SPECS:
            if str(rec.get("element_id") or "").endswith("_" + spec["name"]):
                name = spec["name"]
                break
        answers[name] = parse_region_answer(rec.get("text"))

    values: Dict[str, Tuple[str, str]] = {}
    notes: List[str] = []
    for region_name, mapping in REGION_FIELD_ANSWERS.items():
        parsed = answers.get(region_name)
        if not parsed:
            continue
        for label, field, kind in mapping:
            raw = parsed.get(label)
            if raw is None or _label_key(raw) in _NO_ANSWER:
                continue
            if kind == "date":
                iso = _iso_date(raw)
                if not iso:
                    notes.append(
                        f"region witness read {field} as '{raw}' but that text names "
                        f"no single date; not supplied")
                    continue
                guard = _date_guard(field, iso, raw, parsed, notes)
                if not guard:
                    continue
                values[field] = (iso, raw)
            else:
                values[field] = (raw, raw)
    return values, notes


def _date_guard(field: str, iso: str, raw: str, parsed: Dict[str, str],
                notes: List[str]) -> bool:
    """The two question-shaped guards. Appends its reason to `notes` when it blocks."""
    if field == "pub_date":
        current = parsed.get("currentdate")
        if current and _label_key(current) not in _NO_ANSWER:
            if _iso_date(current) == iso or _label_key(current) == _label_key(raw):
                notes.append(
                    f"region witness read pub_date and the current-date distractor as "
                    f"the SAME date ('{raw}'); the two were asked separately because "
                    f"conflating them is the measured failure, so pub_date is not "
                    f"supplied")
                return False
    if field == "doc_level_ltb_date":
        pairs = _all_dates_pairs(parsed.get("alldates"))
        paired = [d for label, d in pairs
                  if any(k in label for k in _LAST_ORDER_KEYS)]
        if paired and iso not in paired:
            notes.append(
                f"region witness read the last order date as '{raw}' ({iso}) but its "
                f"own row-by-row re-reading pairs that label with "
                f"{', '.join(sorted(set(paired)))}; the disagreement blocks the supply")
            return False
    return True
