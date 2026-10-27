"""The parts crop gets the retry the region read already has.

Measured on onsemi_Generic_IPCN25300X.pdf: the sixth ExtractParts call (the crop carrying
17 of its 19 MPNs) came back HTTP 400 in one fire (0 rows) and a clean-`stop` 8 rows in
another, on byte-identical input, while a third fire returned all 17. These tests pin the
two responses: a fast rejection is retried once (`_extract_parts_once`), and a short crop
is re-sampled once against tier 1's row count, never merged, never made worse.
"""
import pytest

from doc_tools.baml_client import sync_client as sync_client_module
from doc_tools.plugins import sustainment as sustainment_module
from doc_tools.plugins.sustainment import SustainmentPlugin, VISION_MAX_TOKENS

from tests.test_sustainment_plugin import (  # noqa: F401  (fixtures are used by name)
    _part, _table_element, _prompt_from_file, plugin,
)

_400 = RuntimeError("Request failed with status code: 400 Bad Request. "
                    "Failed to load image or audio file")
_FINE = round(VISION_MAX_TOKENS * 0.1)


class SomeTimeoutError(Exception):
    """Class name contains `Timeout`, which is how both retry paths detect one."""


class _RaisingFakeB:
    """Like test_sustainment_plugin._FakeB, but a queued exception instance is raised
    instead of returned. Records how many calls were made."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def ExtractParts(self, **kwargs):
        self.calls += 1
        r = self._results.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


def _install(monkeypatch, results, tokens=_FINE):
    fake = _RaisingFakeB(results)
    monkeypatch.setattr(sync_client_module, "b", fake)
    seq = iter(tokens) if isinstance(tokens, list) else None
    monkeypatch.setattr(sustainment_module, "_vision_output_tokens",
                        (lambda collector: next(seq)) if seq else (lambda collector: tokens))
    return fake


def _rows(n):
    return [_part(f"MPN{i}") for i in range(n)]


def _decline(page=2, n=17):
    return {"page_number": page, "reason": "declined", "n_rows": n, "n_grid_rows": n}


def _run(plugin, elements, declines=None):
    return plugin._extract_parts(elements, None, None, "full text", tl_declines=declines)


# ---- _extract_parts_once ------------------------------------------------------------
def test_a_400_is_retried_once_with_the_same_bytes(plugin, monkeypatch):
    fake = _install(monkeypatch, [_400, _rows(17)])
    parts, stats = _run(plugin, [_table_element(2)])
    assert len(parts) == 17
    assert stats["crops_failed"] == 0
    assert fake.calls == 2


def test_a_timeout_is_not_retried(plugin, monkeypatch):
    fake = _install(monkeypatch, [SomeTimeoutError("read timed out"), _rows(17)])
    parts, stats = _run(plugin, [_table_element(2)])
    assert parts == []
    assert stats["crops_failed"] == 1
    assert fake.calls == 1, "the queued second result must not be consumed"


def test_both_attempts_failing_counts_the_crop_failed(plugin, monkeypatch):
    fake = _install(monkeypatch, [_400, _400])
    parts, stats = _run(plugin, [_table_element(2)])
    assert parts == []
    assert stats["crops_failed"] == 1
    assert fake.calls == 2


# ---- the short-read re-sample -------------------------------------------------------
def test_a_short_read_is_resampled_and_the_second_is_kept(plugin, monkeypatch):
    fake = _install(monkeypatch, [_rows(8), _rows(17)])
    parts, stats = _run(plugin, [_table_element(2)], [_decline()])
    assert len(parts) == 17
    assert stats["crops_row_short"] == 0
    assert stats["crops_resampled"] == 1
    assert stats["crops_resample_recovered"] == 1
    assert stats["resample_detail"] == [{"page_number": 2, "tier1_rows": 17,
                                         "first_rows": 8, "second_rows": 17,
                                         "kept": "second"}]
    assert fake.calls == 2


def test_a_resample_that_does_not_help_keeps_the_first(plugin, monkeypatch):
    _install(monkeypatch, [_rows(8), _rows(8)])
    parts, stats = _run(plugin, [_table_element(2)], [_decline()])
    assert len(parts) == 8, "never merged: two reads of one crop would double shared rows"
    assert stats["crops_row_short"] == 1
    assert stats["crops_resampled"] == 1
    assert stats["crops_resample_recovered"] == 0
    assert stats["resample_detail"][0]["kept"] == "first"


def test_a_resample_that_raises_keeps_the_first_attempts_rows(plugin, monkeypatch):
    _install(monkeypatch, [_rows(8), SomeTimeoutError("read timed out")])
    parts, stats = _run(plugin, [_table_element(2)], [_decline()])
    assert len(parts) == 8
    assert stats["crops_failed"] == 0
    assert stats["crops_row_short"] == 1
    assert stats["resample_detail"][0]["kept"] == "first"


def test_a_truncated_resample_is_refused(plugin, monkeypatch):
    _install(monkeypatch, [_rows(8), _rows(17)], tokens=[_FINE, VISION_MAX_TOKENS])
    parts, stats = _run(plugin, [_table_element(2)], [_decline()])
    assert len(parts) == 8
    assert stats["crops_failed"] == 0
    assert stats["crops_row_short"] == 1
    assert stats["crops_resample_recovered"] == 0
    assert stats["resample_detail"][0]["kept"] == "first"


def test_no_decline_on_the_page_means_no_resample(plugin, monkeypatch):
    fake = _install(monkeypatch, [_rows(2)])
    parts, stats = _run(plugin, [_table_element(2)])
    assert len(parts) == 2
    assert stats["crops_resampled"] == 0
    assert fake.calls == 1


def test_a_later_crop_on_the_same_page_is_not_resampled(plugin, monkeypatch):
    """A later crop of a banded table is expected to return fewer rows than the page
    total; only the page's FIRST successful crop is compared."""
    fake = _install(monkeypatch, [_rows(17), _rows(2)])
    parts, stats = _run(plugin, [_table_element(2), _table_element(2)], [_decline()])
    assert len(parts) == 19
    assert stats["crops_resampled"] == 0
    assert fake.calls == 2
