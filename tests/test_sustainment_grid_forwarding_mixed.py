"""Grid forwarding must be reachable for a MIXED notice: tier 1 emitted >=1 part AND
declined a grid on some other page.

Before this change `_forward_declined_grids` only ran from inside `_extract_parts`, which
the dispatch reached only when tier 1 emitted NOTHING, so a mixed notice's declined grid
was never labeled at all. Forwarding reads every part string verbatim out of the grid
(vision only labels which column index means what), so these tests assert on the ROWS
and not on a count alone -- a stubbed LabelGridColumns says nothing about the prompt.
"""
import pytest

from doc_tools.baml_client import sync_client as sync_client_module
from doc_tools.baml_client.types import GridColumnRoles
from doc_tools.plugins import sustainment as sustainment_module
from doc_tools.plugins.base import PromptUnavailableError
from doc_tools.plugins.sustainment import SustainmentPlugin

GRID_MPNS = ["ZZA-100-1+", "ZZB-200-2+", "ZZC-300-3+"]
TL_MPNS = ["TL-AAA-111", "TL-BBB-222"]


def _tl_part(mpn):
    return {"affected_mpn": mpn, "affected_mpn_source": mpn,
            "replacement_mpn": None, "replacement_mpn_source": None,
            "ltb_date": None, "ltb_date_source": None}


def _grid():
    return [["Affected Part Number", "Replacement"]] + \
           [[f"  {m}  ", f"REPL-{i}"] for i, m in enumerate(GRID_MPNS)]


def _decline(page_number=4):
    grid = _grid()
    return {"page_number": page_number, "reason": "no column header",
            "n_rows": len(GRID_MPNS), "n_grid_rows": len(grid), "grid": grid}


def _roles(affected_col=0, replacement_col=1, ltb_date_col=None, header_rows=(0,)):
    return GridColumnRoles(affected_col=affected_col, replacement_col=replacement_col,
                           ltb_date_col=ltb_date_col, header_rows=list(header_rows),
                           reason="stub")


class _FakeB:
    def __init__(self, label_results=()):
        self._label_results = list(label_results)
        self.label_calls = []
        self.extract_parts_calls = 0

    def LabelGridColumns(self, **kwargs):
        self.label_calls.append(kwargs)
        result = self._label_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def ExtractParts(self, **kwargs):
        self.extract_parts_calls += 1
        return []


@pytest.fixture(autouse=True)
def _prompt_from_file(monkeypatch):
    monkeypatch.setenv("PROMPT_SOURCE", "file")
    monkeypatch.setattr(sustainment_module, "_vision_output_tokens", lambda collector: 10)


@pytest.fixture
def plugin():
    return SustainmentPlugin(domain_type="sustainment")


def _install_fake(monkeypatch, **kw):
    fake = _FakeB(**kw)
    monkeypatch.setattr(sync_client_module, "b", fake)
    return fake


def _run(plugin, monkeypatch, tl_parts, declines, vision=True, s3_client=object()):
    monkeypatch.setattr(
        plugin, "_extract_parts_text_layer",
        lambda manifest, s3, bucket: (list(tl_parts), {
            "text_layer_pages": 1, "text_layer_parts": len(tl_parts),
            "text_layer_used": bool(tl_parts), "text_layer_declines": declines}))
    monkeypatch.setattr(plugin, "_extract_header", lambda full_text: None)
    if vision:
        monkeypatch.setenv("VISION_LLM_BASE_URL", "http://fake-vision")
    else:
        monkeypatch.delenv("VISION_LLM_BASE_URL", raising=False)
    # NO Table element on the declined page: forwarding must not need one.
    nodes = plugin._extract_fulltext(
        "full text", "DOC1", metadata=None, elements=[],
        manifest={"source_key": "notice.pdf"}, s3_client=s3_client, bucket="bucket")
    return nodes[0].domain_augmentation


def _mpns(aug):
    return [p.affected_mpn for p in aug.notice.impacted_parts]


def test_mixed_notice_forwards_declined_grid_verbatim(plugin, monkeypatch):
    fake = _install_fake(monkeypatch, label_results=[_roles()])
    aug = _run(plugin, monkeypatch, [_tl_part(m) for m in TL_MPNS], [_decline()])

    assert _mpns(aug) == TL_MPNS + GRID_MPNS, "tier-1 first, forwarded rows appended"
    assert len(aug.notice.impacted_parts) == 5
    for p in aug.notice.impacted_parts[2:]:
        assert p.affected_mpn == p.affected_mpn_source
    assert [p.replacement_mpn for p in aug.notice.impacted_parts[2:]] == \
        ["REPL-0", "REPL-1", "REPL-2"]
    assert aug.stats["grid_forwarded_mixed"] == 3
    assert "rows_by_page" not in aug.stats
    assert len(fake.label_calls) == 1
    assert fake.extract_parts_calls == 0


def test_no_declines_makes_no_baml_call(plugin, monkeypatch):
    fake = _install_fake(monkeypatch)
    aug = _run(plugin, monkeypatch, [_tl_part(m) for m in TL_MPNS], [])
    assert fake.label_calls == []
    assert _mpns(aug) == TL_MPNS
    assert "grid_forwarded_mixed" not in aug.stats


@pytest.mark.parametrize("vision,s3", [(False, object()), (True, None)])
def test_vision_unavailable_is_a_silent_noop(plugin, monkeypatch, vision, s3):
    fake = _install_fake(monkeypatch, label_results=[_roles()])
    aug = _run(plugin, monkeypatch, [_tl_part(m) for m in TL_MPNS], [_decline()],
               vision=vision, s3_client=s3)
    assert fake.label_calls == []
    assert _mpns(aug) == TL_MPNS
    assert not aug.stats.get("grid_forwarded_mixed")
    for k in ("grid_forwarded", "grid_label_failed", "grid_rows_emitted", "grid_no_parts_col"):
        assert aug.stats[k] == 0


@pytest.mark.parametrize("result", [
    RuntimeError("model host down"),
    _roles(affected_col=9),  # out of range for a 2-column grid
], ids=["label-failure", "out-of-range-index"])
def test_label_failure_leaves_tier1_parts_untouched(plugin, monkeypatch, result):
    _install_fake(monkeypatch, label_results=[result])
    aug = _run(plugin, monkeypatch, [_tl_part(m) for m in TL_MPNS], [_decline()])
    assert _mpns(aug) == TL_MPNS
    assert aug.stats["grid_forwarded_mixed"] == 0
    assert aug.stats["grid_label_failed"] == 1


def test_affected_col_none_counts_no_parts_col_and_appends_nothing(plugin, monkeypatch):
    _install_fake(monkeypatch, label_results=[_roles(affected_col=None)])
    aug = _run(plugin, monkeypatch, [_tl_part(m) for m in TL_MPNS], [_decline()])
    assert _mpns(aug) == TL_MPNS
    assert aug.stats["grid_no_parts_col"] == 1
    assert aug.stats["grid_forwarded_mixed"] == 0


def test_extract_parts_without_tier1_parts_forwards_the_same_rows(plugin, monkeypatch):
    """Refactor equivalence: the vision path's own forwarding is unchanged in shape."""
    _install_fake(monkeypatch, label_results=[_roles()])
    parts, stats = plugin._extract_parts(
        [{"type": "Table", "text": "t", "metadata": {"page_number": 4, "text_as_html": ""}}],
        None, None, "full text", tl_declines=[_decline()])
    assert [p["affected_mpn"] for p in parts] == GRID_MPNS
    assert [p["affected_mpn_source"] for p in parts] == GRID_MPNS
    assert stats["grid_forwarded"] == 1
    assert stats["grid_rows_emitted"] == 3
    assert stats["grid_label_failed"] == 0
    assert stats["crops_row_short"] == 0


def test_prompt_unavailable_propagates_from_the_mixed_path(plugin, monkeypatch):
    _install_fake(monkeypatch, label_results=[_roles()])

    def boom(*a, **k):
        raise PromptUnavailableError("grid prompt missing")

    monkeypatch.setattr(plugin, "_get_dynamic_prompt", boom)
    with pytest.raises(PromptUnavailableError):
        _run(plugin, monkeypatch, [_tl_part(m) for m in TL_MPNS], [_decline()])


def test_generic_failure_records_a_reason_but_does_not_flip_needs_review(plugin, monkeypatch):
    # Baseline: the same document with forwarding switched off.
    _install_fake(monkeypatch)
    baseline = _run(plugin, monkeypatch, [_tl_part(m) for m in TL_MPNS], [_decline()],
                    vision=False)

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(plugin, "_forward_declined_grids", boom)
    aug = _run(plugin, monkeypatch, [_tl_part(m) for m in TL_MPNS], [_decline()])
    assert _mpns(aug) == TL_MPNS
    assert any("kaboom" in r for r in aug.review_reasons)
    assert aug.needs_review == baseline.needs_review
