"""The header witness reads CROPS, and these pin how the crops are chosen.

The defect this module answers was measured against the live vision host on
TYC-PCN-24-210412 (2026-10-01): asked about the WHOLE page, the model answers
`10-Jan-2024` for a date the page prints as `10-Jun-2024` -- twice, one-shot and
multi-turn -- and asked about a CROP of the header block on the same page, same
model, same host, it answers `10-Jun-2024`. Raising the page render from 150 to
200 DPI fixed two other dates on that page and never fixed this one.

The geometry in `TYC_PAGE1` below is REAL: element boxes taken from a live
hi_res extraction of that notice, converted into the layout-pixel space
`provenance.build_positioned_index` stores (1700x2200 for Letter). The text is
the real text too, including its damage -- that layer loses every `ti`, so it
reads "Esmated Dates:" and "TE Connecvity". Keeping the fixture faithful is the
point: a synthetic fixture with clean spellings would pass against a locator
that cannot find this block on the one document the witness exists for.
"""
import pytest

from doc_tools.utils import witness_regions as wr

ROOT_PROMPT = "prompts/sustainment_read_region.md"


def _rec(element_id, type_, bbox, text, page=1):
    """A positioned-index record, shaped as provenance.build_positioned_index makes them."""
    return {
        "element_id": element_id,
        "type": type_,
        "region": "table" if type_ == "Table" else "narrative",
        "page_number": page,
        "bbox": list(bbox),
        "page_width": 1700,
        "page_height": 2200,
        "text": text,
        "text_as_html": "",
    }


# Real geometry and real (damaged) text from TYC-PCN-24-210412 page 1.
TYC_PAGE1 = [
    _rec("el_0", "Header", (70.0, 42.4, 249.4, 65.0), "6/10/24, 11:28 AM"),
    _rec("el_1", "NarrativeText", (70.0, 70.0, 1620.1, 95.0),
         "te.com/commerce/pcnws/PCNSecurityController?pcndate=07-JUN-24&pcnnbr=PCN-24-210412"),
    _rec("el_2", "Title", (101.4, 180.0, 700.0, 200.0), "Product Change Noficaon"),
    _rec("el_3", "NarrativeText", (101.4, 240.0, 600.0, 260.0), "Current Date: 10-Jun-2024"),
    _rec("el_4", "NarrativeText", (101.4, 300.0, 400.0, 320.0), "TE Connecvity"),
    _rec("el_5", "NarrativeText", (101.4, 360.0, 1200.0, 380.0),
         "Product Change Noficaon: PCN-24-210412 PCN Date: 07-JUN-24"),
    _rec("el_6", "NarrativeText", (101.4, 420.0, 1500.0, 484.6),
         "Customer: TTI Inc ( 1305175 ) Locaon: Maisach-gernlinden"),
    # The first table on the page: the cut line for the header block.
    _rec("el_7", "Table", (91.4, 535.0, 1593.9, 1094.7), "PCN Aributes: Product Category:"),
    _rec("el_8", "UncategorizedText", (101.4, 809.4, 278.9, 830.6), "Reason for Changes:"),
    # The dates block: a bare caption, an overlapping grid, then label/value rows.
    _rec("el_9", "UncategorizedText", (101.4, 1152.2, 248.9, 1173.3), "Esmated Dates:"),
    _rec("el_10", "Table", (108.1, 1165.8, 1590.0, 1332.0),
         "First Ship Date of Changed Items (Changed Parts Only): Last Date for Mixed Shipments:"),
    _rec("el_11", "UncategorizedText", (101.4, 1182.5, 430.8, 1203.6),
         "Last Order Date (Obsolete Parts Only):"),
    _rec("el_12", "UncategorizedText", (101.4, 1212.5, 212.5, 1233.9), "06-JUN-2024"),
    _rec("el_13", "UncategorizedText", (101.4, 1242.8, 575.3, 1263.9),
         "Last Ship Date of Changed Items (Obsolete Parts Only):"),
    _rec("el_14", "UncategorizedText", (101.4, 1273.1, 212.5, 1294.2), "07-JUN-2024"),
    # The next SECTION: 18 pt below the last dates row, which is why the walk
    # forward stops at a heading rather than at a vertical gap.
    _rec("el_15", "Title", (95.3, 1381.9, 377.0, 1404.4), "Part Number(s) being Modified:"),
    _rec("el_16", "Table", (89.7, 1409.2, 1600.8, 2010.6), "Part Number Part Disconnued per PCN"),
]


# --------------------------------------------------------------------------- #
# The fold
# --------------------------------------------------------------------------- #
class TestFoldLigatures:
    def test_the_literal_search_is_the_trap_the_fold_exists_for(self):
        """Verified against the real document: literal 0 hits, folded 1 hit.

        This is the whole reason the locator folds. A damaged layer renders
        "Estimated Dates:" as "Esmated Dates:", so a locator matching the
        obvious literal finds the dates block on every notice EXCEPT the one the
        witness was built to rescue.
        """
        damaged = "Esmated Dates:"
        assert "estimated dates" not in damaged.lower()
        assert wr.fold_ligatures("Estimated Dates") in wr.fold_ligatures(damaged)

    def test_fold_is_idempotent_across_the_damage(self):
        """Clean and damaged spellings must reach the SAME key, or the locator
        would have to know in advance which documents are damaged."""
        assert wr.fold_ligatures("Estimated Dates") == wr.fold_ligatures("Esmated Dates")
        assert wr.fold_ligatures("TE Connectivity") == wr.fold_ligatures("TE Connecvity")
        assert wr.fold_ligatures("Notification") == wr.fold_ligatures("Noficaon")

    def test_control_bytes_are_stripped(self):
        """pdfplumber reports the dropped glyph as a NUL where unstructured drops
        it outright; both readings of the same page must fold alike."""
        assert wr.fold_ligatures("Es\x00mated Dates") == wr.fold_ligatures("Estimated Dates")

    def test_longest_ligature_first(self):
        """A naive alternation takes "fi" out of "ffi" and leaves a stray "f"."""
        assert "f" not in wr.fold_ligatures("ffi")

    def test_fold_handles_none_and_empty(self):
        assert wr.fold_ligatures(None) == ""
        assert wr.fold_ligatures("") == ""


# --------------------------------------------------------------------------- #
# Locating
# --------------------------------------------------------------------------- #
class TestLocateHeaderBlock:
    def test_header_block_stops_at_the_first_table(self):
        r = wr.locate_header_block(TYC_PAGE1)
        assert r is not None
        # Everything above the first table (y=535) and nothing below it.
        assert r["bbox"][3] <= 535.0
        assert r["bbox"][1] <= 42.4

    def test_header_block_contains_every_field_it_claims_to_answer(self):
        """The crop has to physically contain mfr, doc_id, pub_date -- and the
        Current Date distractor, which the prompt asks about SEPARATELY so the
        model reports it instead of mistaking it for the publication date."""
        r = wr.locate_header_block(TYC_PAGE1)
        x0, y0, x1, y1 = r["bbox"]
        for el in (TYC_PAGE1[3], TYC_PAGE1[4], TYC_PAGE1[5]):  # Current Date, mfr, doc_id
            b = el["bbox"]
            assert x0 <= b[0] and y0 <= b[1] and x1 >= b[2] and y1 >= b[3], (
                f"{el['text']!r} falls outside the header crop"
            )

    def test_a_header_block_is_never_most_of_the_page(self):
        """Prose running down to a table at the foot of the page would otherwise
        make the "crop" nearly the whole page, silently restoring the very
        whole-page defect this module exists to fix."""
        els = [_rec("a", "NarrativeText", (100.0, 50.0, 1600.0, 100.0), "masthead"),
               _rec("b", "NarrativeText", (100.0, 1800.0, 1600.0, 1900.0), "prose, low"),
               _rec("c", "Table", (100.0, 2100.0, 1600.0, 2190.0), "a table at the foot")]
        r = wr.locate_header_block(els)
        assert (r["bbox"][3] - r["bbox"][1]) / 2200.0 <= wr._HEADER_MAX_FRACTION
        assert "band" in r["located_by"]

    def test_a_sparse_masthead_keeps_its_tight_union(self):
        """The clamp is a ceiling, not a floor: one element above a far-down
        table yields a crop as tight as that element, not the whole top third."""
        els = [_rec("a", "NarrativeText", (100.0, 50.0, 1600.0, 100.0), "masthead"),
               _rec("b", "Table", (100.0, 2100.0, 1600.0, 2190.0), "a table at the foot")]
        r = wr.locate_header_block(els)
        assert r["bbox"] == [100.0, 50.0, 1600.0, 100.0]
        assert "above the first table" in r["located_by"]

    def test_no_table_falls_back_to_the_top_band(self):
        els = [_rec("a", "NarrativeText", (100.0, 50.0, 1600.0, 100.0), "masthead")]
        r = wr.locate_header_block(els)
        assert r is not None
        assert r["bbox"][3] == pytest.approx(2200.0 * wr._HEADER_FALLBACK_FRACTION)

    def test_no_geometry_locates_nothing(self):
        """An index with no coordinates must not produce a box over nothing."""
        assert wr.locate_header_block([]) is None
        blind = [dict(_rec("a", "Text", (0, 0, 1, 1), "x"), bbox=None)]
        assert wr.locate_header_block(blind) is None


class TestLocateEstimatedDates:
    def test_bare_caption_is_extended_to_the_rows_it_captions(self):
        """The label is its OWN element here, 147x21 layout px, carrying no date.
        A crop of just that element would contain nothing worth asking about."""
        r = wr.locate_estimated_dates(TYC_PAGE1)
        assert r is not None
        assert r["bbox"][1] <= 1152.2
        for el in (TYC_PAGE1[12], TYC_PAGE1[14]):  # 06-JUN-2024, 07-JUN-2024
            b = el["bbox"]
            assert r["bbox"][1] <= b[1] and r["bbox"][3] >= b[3], (
                f"{el['text']!r} falls outside the dates crop"
            )

    def test_the_walk_stops_at_the_next_section_heading(self):
        """"Part Number(s) being Modified:" sits 18 pt below the last dates row --
        close enough that any vertical-gap rule loose enough to keep the rows
        would also swallow the next section and its 600 pt table."""
        r = wr.locate_estimated_dates(TYC_PAGE1)
        assert r["bbox"][3] < TYC_PAGE1[15]["bbox"][1], "pulled in the next section"
        assert "section heading" in r["located_by"]

    def test_the_crop_stays_a_crop(self):
        """Bounded area is the mechanism; a dates crop covering most of the page
        would be the whole-page read under another name."""
        r = wr.locate_estimated_dates(TYC_PAGE1)
        h = (r["bbox"][3] - r["bbox"][1]) / 2200.0
        assert h < 0.15, f"dates crop is {h:.0%} of the page height"

    def test_label_variants_are_all_found(self):
        for label in ("Estimated Dates:", "Key Dates", "Important Dates",
                      "Last Order Date (Obsolete Parts Only):"):
            els = [_rec("a", "UncategorizedText", (100.0, 500.0, 400.0, 520.0), label),
                   _rec("b", "UncategorizedText", (100.0, 530.0, 300.0, 550.0), "06-JUN-2024")]
            assert wr.locate_estimated_dates(els) is not None, label

    def test_prose_mentioning_an_estimated_date_is_not_a_dates_block(self):
        """Notice prose routinely says "the estimated date of the first shipment
        is stated in the attached schedule". That matches the label and contains
        no dates block, so cropping it would spend a vision call asking a
        sentence for two dates."""
        els = [_rec("a", "NarrativeText", (100.0, 500.0, 1600.0, 600.0),
                    "There is no change to form, fit or function. The estimated date "
                    "of the first shipment from the new location is stated in the "
                    "attached schedule, together with the last time buy instructions.")]
        assert wr.locate_estimated_dates(els) is None

    def test_a_grid_whose_own_text_carries_the_label_is_accepted(self):
        """The counterpart to the rule above: a Table is a dates block however
        long its flattened text runs, because that text IS the grid."""
        els = [_rec("t", "Table", (100.0, 500.0, 1600.0, 700.0),
                    "Estimated Dates: Last Order Date (Obsolete Parts Only): 06-JUN-2024 "
                    "Last Ship Date of Changed Items (Obsolete Parts Only): 07-JUN-2024 "
                    "First Ship Date of Changed Items (Changed Parts Only): No Mixed")]
        r = wr.locate_estimated_dates(els)
        assert r is not None and r["bbox"] == [100.0, 500.0, 1600.0, 700.0]

    def test_a_document_without_a_dates_block_locates_nothing(self):
        """Most notices have no dates block at all; inventing a box for them
        would spend a vision call on a crop of whatever happened to be there."""
        els = [_rec("a", "NarrativeText", (100.0, 50.0, 1600.0, 100.0), "no dates here"),
               _rec("b", "Table", (100.0, 200.0, 1600.0, 900.0), "Part Number Quantity")]
        assert wr.locate_estimated_dates(els) is None

    def test_a_later_page_is_searched_too(self):
        els = [_rec("a", "NarrativeText", (100.0, 50.0, 1600.0, 100.0), "page one", page=1),
               _rec("b", "UncategorizedText", (100.0, 500.0, 400.0, 520.0),
                    "Esmated Dates:", page=3),
               _rec("c", "UncategorizedText", (100.0, 530.0, 300.0, 550.0),
                    "06-JUN-2024", page=3)]
        r = wr.locate_estimated_dates(els)
        assert r is not None and r["page_number"] == 3


class TestLocateRegions:
    def test_both_regions_on_the_real_notice(self):
        regions = wr.locate_regions(TYC_PAGE1)
        assert [r["name"] for r in regions] == ["header_block", "estimated_dates"]

    def test_every_region_declares_the_fields_it_answers(self):
        """`fields` is the coverage this module owes the header refusal. A field
        silently losing its witness should fail here, not quietly stop being
        corroborated in production."""
        covered = {f for r in wr.locate_regions(TYC_PAGE1) for f in r["fields"]}
        assert {"mfr", "doc_id", "pub_date", "doc_level_ltb_date"} <= covered

    def test_an_unlocatable_region_is_omitted_not_empty(self):
        """A notice with no dates block yields one region, not a region with a
        meaningless box -- the witness loses the field, not the document."""
        els = [_rec("a", "NarrativeText", (100.0, 50.0, 1600.0, 100.0), "masthead"),
               _rec("b", "Table", (100.0, 300.0, 1600.0, 900.0), "Part Number")]
        names = [r["name"] for r in wr.locate_regions(els)]
        assert names == ["header_block"]

    def test_located_by_is_recorded(self):
        """A surprising crop must be explainable from the record alone, without
        re-running the locator against a document that may have been re-ingested."""
        for r in wr.locate_regions(TYC_PAGE1):
            assert r["located_by"]


# --------------------------------------------------------------------------- #
# Layout pixels -> raster pixels
# --------------------------------------------------------------------------- #
class TestRegionPixelBox:
    def test_scales_from_layout_space_to_the_raster(self):
        """1700x2200 layout -> a 2550x3300 raster (Letter at 300 DPI) is 1.5x."""
        r = wr.locate_estimated_dates(TYC_PAGE1)
        box = wr.region_pixel_box(r, 2550, 3300)
        assert box is not None
        pad = 0.01 * 3300
        assert box[0] == pytest.approx(round(r["bbox"][0] * 1.5 - pad), abs=1)
        assert box[3] == pytest.approx(round(r["bbox"][3] * 1.5 + pad), abs=1)

    def test_the_box_is_inside_the_image(self):
        """Padding must never push the crop off the raster; PIL would happily
        return a smaller image and the crop would be silently shifted."""
        els = [_rec("a", "NarrativeText", (0.0, 0.0, 1700.0, 2200.0), "the whole page")]
        box = wr.region_pixel_box(wr.locate_header_block(els), 2550, 3300)
        assert box[0] >= 0 and box[1] >= 0 and box[2] <= 2550 and box[3] <= 3300

    def test_mismatched_aspect_ratios_refuse_rather_than_misplace(self):
        """If the raster and the text layer are not framing the same page, a
        scaled box is confidently wrong. Refusing costs the region; guessing
        costs the answer, invisibly."""
        r = wr.locate_header_block(TYC_PAGE1)
        assert wr.region_pixel_box(r, 2550, 1200) is None

    def test_a_degenerate_box_is_refused(self):
        tiny = {"bbox": [10.0, 10.0, 12.0, 12.0], "page_width": 1700, "page_height": 2200}
        assert wr.region_pixel_box(tiny, 170, 220) is None

    def test_missing_page_dims_are_refused(self):
        assert wr.region_pixel_box({"bbox": [0, 0, 10, 10]}, 2550, 3300) is None

    def test_pad_scales_with_the_render(self):
        """The pad is a FRACTION of page height, so it stays ~8 pt at any DPI --
        a DPI-derived constant would need the manifest's dpi field, which can be
        stale, to stay correct."""
        r = wr.locate_estimated_dates(TYC_PAGE1)
        small = wr.region_pixel_box(r, 1700, 2200)
        large = wr.region_pixel_box(r, 2550, 3300)
        assert (large[3] - large[1]) / (small[3] - small[1]) == pytest.approx(1.5, abs=0.02)


# --------------------------------------------------------------------------- #
# Prompt sections
# --------------------------------------------------------------------------- #
class TestPromptSections:
    def _markdown(self):
        from pathlib import Path
        return (Path(__file__).resolve().parents[1] / ROOT_PROMPT).read_text(encoding="utf-8")

    def test_the_committed_prompt_resolves_every_region(self):
        """CI catches a missing section, so production never discovers it inside a
        vision call. A call made with no instructions does not fail -- it answers
        something, and the run reads as a near-pass."""
        wr.validate_region_prompt(self._markdown())

    def test_a_missing_section_raises_rather_than_returning_empty(self):
        with pytest.raises(ValueError, match="no '## nope' section"):
            wr.region_prompt("## common\nbe careful\n", "nope")

    def test_common_is_prepended_to_each_section(self):
        md = "## common\nSHARED RULE\n\n## header_block\nASK THIS\n"
        out = wr.region_prompt(md, "header_block")
        assert out.index("SHARED RULE") < out.index("ASK THIS")

    def test_the_header_prompt_separates_the_notice_date_from_the_print_stamp(self):
        """The distractor is the measured failure: TYC prints both its own
        07-JUN-24 issue date and a 10-Jun-2024 portal stamp, and ground truth
        files the stamp under `not`. The prompt must ask for them separately or
        the witness can corroborate the wrong one."""
        text = wr.region_prompt(self._markdown(), "header_block")
        assert "Current Date:" in text
        assert "Notice Date:" in text

    def test_the_dates_prompt_asks_for_every_labelled_pair(self):
        """Mispairing adjacent rows is the failure mode here -- the real block
        has 06-JUN-2024 and 07-JUN-2024 one row apart. Asking for all labelled
        pairs makes a mispairing visible instead of silent."""
        text = wr.region_prompt(self._markdown(), "estimated_dates")
        assert "All Dates:" in text

    def test_verbatim_is_demanded_of_both_regions(self):
        """A normalised date cannot be checked against the page by containment."""
        md = self._markdown()
        for spec in wr.REGION_SPECS:
            assert "VERBATIM" in wr.region_prompt(md, spec["prompt_section"]).upper()
