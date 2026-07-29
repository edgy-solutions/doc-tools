"""normalize_doc_id: one key-safe notice identifier from messy sources.

History (2026-07-28): doc_id flows into the grouped-review workflow id, the MinIO
artifact-prefix lookup, the SUSTAINMENT graph IRI, and the provenance index — all
KEYS. But its two sources are messy: the header LLM extracts the number 'exactly
as printed' (spaces, '#' — e.g. 'PCN # 23-002') and the path fallback yields a
path fragment ('inbound/adi_23_0120'). Raw, the '#' truncated a Restate ingress
URL as a fragment -> the review-batch call 502'd and the card rendered empty; and
the same document keyed two ways never joined. normalize_doc_id collapses to a
clean, URL/key-safe slug at finalization so every consumer keys on the same value.
"""
import pytest

from doc_tools.utils.sustainment_normalize import normalize_doc_id


@pytest.mark.parametrize("raw, expected", [
    ("PCN # 23-002", "PCN-23-002"),          # spaces + '#' (the 502 case)
    ("PCN # 23-0171", "PCN-23-0171"),
    ("inbound/adi_23_0120", "adi_23_0120"),  # path-derived fallback -> last segment
    ("PDN 23_0120", "PDN-23_0120"),          # space -> dash, '_' kept
    ("IPCN25300X", "IPCN25300X"),            # already clean -> unchanged
    ("PCN20250409000.1", "PCN20250409000.1"),  # dots kept
    ("PCN-2683", "PCN-2683"),                # already clean
    ("  PCN 42  ", "PCN-42"),                # trimmed
    ("", "unknown"),                          # empty -> honest placeholder
    (None, "unknown"),
])
def test_normalize_doc_id_cases(raw, expected):
    assert normalize_doc_id(raw) == expected


def test_output_is_always_url_and_key_safe():
    """The whole point: no output may contain a space, '#', '/', or quote — the
    characters that break a Restate ingress URL / a graph IRI."""
    for raw in ["PCN # 23-002", "inbound/adi_23_0120", 'a "quoted" id', "x/y/z 1#2"]:
        out = normalize_doc_id(raw)
        assert not any(c in out for c in ' #/"'), f"{raw!r} -> {out!r} still unsafe"


def test_idempotent():
    """Normalizing an already-normalized id returns it unchanged — so the graph-IRI
    site can re-apply it safely on top of the finalized doc_id."""
    for raw in ["PCN # 23-002", "inbound/adi_23_0120", "IPCN25300X"]:
        once = normalize_doc_id(raw)
        assert normalize_doc_id(once) == once


def test_does_not_collide_distinct_notices():
    """Distinct real notice numbers must stay distinct after normalization."""
    ids = ["PCN # 23-002", "PCN # 23-0171", "PCN-2683", "IPCN25300X", "PDN 23_0120"]
    slugs = [normalize_doc_id(i) for i in ids]
    assert len(set(slugs)) == len(ids)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
