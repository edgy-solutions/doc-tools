"""The witness's page raster must not be rendered lighter than the table crops.

Why this is pinned rather than left to a default nobody reads: the SUSTAINMENT
second witness (``SustainmentPlugin._transcribe_pages_witness``) transcribes the
WHOLE-PAGE raster produced by ``rasterize_pdf_pages`` in order to corroborate
header dates. That raster used to be rendered at 150 DPI on the rationale --
still in the docstring until 2026-10-01 -- that the page is "context, not the
row-level read". The witness made it a row-level read.

Measured 2026-10-01 against the live vision host on ``TYC-PCN-24-210412.pdf``:
at 150 DPI the model collapsed a wrapped two-column Estimated Dates grid onto
its label line AND substituted digits (06-JUN -> 08-JUN, 07-JUN -> 02-JUN); at
200 DPI, with the prompt, model and host held fixed, it read both correctly.
Holding the IMAGE fixed and swapping the prompt instead reproduced the error, so
the render is the cause.

It is now 300, for a second reason that outranks the first: ``witness_regions``
cuts the header-block and dates-block CROPS the header witness reads out of this
same raster, and a crop cannot be sharper than the image it came from. The
whole-page transcription is in fact slightly WORSE at 300 than at 200, but it no
longer answers header questions -- it corroborates part numbers -- so the page
call pays latency and every crop gains detail.

A regression here is SILENT: the dates simply come back wrong, the witness still
answers, and header corroboration is quietly degraded rather than failing. And
the raster is written at INGEST, so by the time anyone notices, fixing the
default does nothing until every document is re-ingested. Hence a test.
"""

import re
from pathlib import Path

from doc_tools.utils.extraction import rasterize_pdf_pages

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "doc-tools"
PARSER = ROOT / "doc_tools" / "components" / "document_parser.py"


def _default_dpi(func):
    """The ``dpi`` keyword default of a function, read off its signature."""
    import inspect

    return inspect.signature(func).parameters["dpi"].default


def test_page_render_default_is_300():
    assert _default_dpi(rasterize_pdf_pages) == 300, (
        "rasterize_pdf_pages' dpi default is the source image for the header "
        "witness's region crops; at 150 it misread two dates on TYC page 1, and "
        "a crop cannot be sharper than the raster it is cut from"
    )


def test_page_render_is_not_lighter_than_the_crops():
    """The invariant, independent of the specific number.

    The crops are the DETAIL half of the evidence card and the page the CONTEXT
    half, but the witness reads the page at row level, so the page must be at
    least as legible as the crops. Both defaults live in document_parser.py.
    """
    src = PARSER.read_text(encoding="utf-8")
    page = re.search(r'DOC_PARSER_PAGE_RENDER_DPI",\s*"(\d+)"', src)
    crop = re.search(r'DOC_PARSER_PDF_IMAGE_DPI",\s*"(\d+)"', src)
    assert page and crop, "both DPI env defaults must stay readable here"
    assert int(page.group(1)) >= int(crop.group(1)), (
        f"page render {page.group(1)} DPI is lighter than the crops at "
        f"{crop.group(1)}; the witness transcribes the page"
    )


def test_chart_sets_the_page_render_dpi_explicitly():
    """Deployed value, not just the code default.

    The chart already pins DOC_PARSER_PDF_IMAGE_DPI even though the code agrees;
    the page knob gets the same treatment so the number a cluster runs is
    reviewable in the diff rather than implied.
    """
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    assert 'DOC_PARSER_PAGE_RENDER_DPI: "300"' in values


def test_env_override_still_wins():
    """The pin is a default, not a hardcode -- an operator can still raise it."""
    src = PARSER.read_text(encoding="utf-8")
    assert 'int(os.getenv("DOC_PARSER_PAGE_RENDER_DPI", "300"))' in src, (
        "the DPI must stay an env read, not an inlined constant"
    )
