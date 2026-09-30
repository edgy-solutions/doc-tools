"""`find_manifests` (scripts/pcn_corpus_run.py) must resolve versioned artifact layout.

document_parser.py now writes every generated artifact under a `{version}` path segment
and only points to the live one via `current.json` (doc_tools/components/document_parser.py).
Before this fix, `find_manifests` globbed every key ending `/manifest.json` — which, once a
notice has been reprocessed even once, matches BOTH the legacy unversioned manifest AND one
per historical version, and silently kept whichever the dict-building loop saw last. That's
a real, silent wrong-version bug: the harness would score whatever version happened to sort
last, not the live one.

Backward compatibility is mandatory — the 9 real notices in MinIO have no current.json and
no migration is planned, so a legacy manifest.json sitting directly in
`generated/{base_name}/` must still resolve.

Imported by path, like test_corpus_import_provenance.py: `scripts/` is not a package.
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BUCKET = "processing-artifacts"


@pytest.fixture(scope="module")
def runner():
    pytest.importorskip("boto3", reason="the corpus driver imports boto3 at module level")
    spec = importlib.util.spec_from_file_location("pcn_corpus_run", SCRIPTS / "pcn_corpus_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeS3:
    """`objects` maps a full S3 key to a dict (JSON body). Enough to drive
    `list_objects_v2` (unpaginated — one page is plenty for these fixtures) and
    `get_object` without a real bucket."""

    def __init__(self, objects):
        self.objects = objects

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def get_object(self, Bucket, Key):
        body = json.dumps(self.objects[Key]).encode("utf-8")
        return {"Body": SimpleNamespace(read=lambda: body)}


LEGACY_OBJECTS = {
    "sustainment/inbound/legacy1/generated/Legacy_One_pdf/manifest.json": {
        "filename": "Legacy_One.pdf",
        "text_location": "sustainment/inbound/legacy1/generated/Legacy_One_pdf/text.json",
    },
}

VERSIONED_OBJECTS = {
    # The live pointer.
    "sustainment/inbound/ver1/generated/Ver_One_pdf/current.json": {
        "pipeline_version": "doc-tools@v2",
        "manifest_key": "sustainment/inbound/ver1/generated/Ver_One_pdf/doc-tools@v2/manifest.json",
        "updated_at": "2026-09-30T00:00:00+00:00",
    },
    # The CURRENT version's manifest — this is what current.json points at.
    "sustainment/inbound/ver1/generated/Ver_One_pdf/doc-tools@v2/manifest.json": {
        "filename": "Ver_One.pdf",
        "text_location": "sustainment/inbound/ver1/generated/Ver_One_pdf/doc-tools@v2/text.json",
    },
    # A STALE prior version's manifest, still sitting in the bucket (nothing deletes
    # it). Naive globbing would surface this as a second candidate for the same
    # filename; it must NOT appear at all once current.json is honored.
    "sustainment/inbound/ver1/generated/Ver_One_pdf/doc-tools@v1/manifest.json": {
        "filename": "Ver_One.pdf",
        "text_location": "sustainment/inbound/ver1/generated/Ver_One_pdf/doc-tools@v1/text.json",
    },
}


def test_find_manifests_resolves_via_current_json(runner):
    c = _FakeS3(dict(VERSIONED_OBJECTS))
    by_file = runner.find_manifests(c)

    assert list(by_file.keys()) == ["Ver_One.pdf"]
    cands = by_file["Ver_One.pdf"]
    assert len(cands) == 1, (
        f"expected exactly one candidate via current.json, got {len(cands)}: "
        f"{[k for k, _m in cands]} — the stale prior-version manifest must not surface"
    )
    key, m = cands[0]
    assert key == "sustainment/inbound/ver1/generated/Ver_One_pdf/doc-tools@v2/manifest.json"
    assert m["text_location"] == "sustainment/inbound/ver1/generated/Ver_One_pdf/doc-tools@v2/text.json"


def test_find_manifests_still_finds_legacy_notice_without_current_json(runner):
    c = _FakeS3(dict(LEGACY_OBJECTS))
    by_file = runner.find_manifests(c)

    assert list(by_file.keys()) == ["Legacy_One.pdf"]
    cands = by_file["Legacy_One.pdf"]
    assert len(cands) == 1
    key, m = cands[0]
    assert key == "sustainment/inbound/legacy1/generated/Legacy_One_pdf/manifest.json"
    assert m["filename"] == "Legacy_One.pdf"


def test_find_manifests_mixed_corpus_finds_both_exactly_once(runner):
    combined = {**LEGACY_OBJECTS, **VERSIONED_OBJECTS}
    c = _FakeS3(combined)
    by_file = runner.find_manifests(c)

    assert set(by_file.keys()) == {"Legacy_One.pdf", "Ver_One.pdf"}
    assert len(by_file["Legacy_One.pdf"]) == 1
    assert len(by_file["Ver_One.pdf"]) == 1


def test_pick_prefer_pin_survives_reprocess_of_the_pinned_directory(runner, monkeypatch):
    """PREFER pins a document directory by its (pre-versioning) exact manifest.json key.
    Once that SAME directory is reprocessed under the versioned layout, find_manifests()
    only surfaces the new `.../{version}/manifest.json` candidate for it — the literal
    legacy key PREFER names no longer appears among the candidates at all. pick() must
    still recognize the pin (by directory prefix) rather than silently falling through
    to the lexical-first fallback, which would look like an unexplained corpus
    regression."""
    fn = "Pinned_Notice.pdf"
    pinned_dir = "sustainment/inbound/pinned_copy/generated/Pinned_Notice_pdf"
    other_dir = "sustainment/inbound/other_copy/generated/Pinned_Notice_pdf"
    monkeypatch.setitem(runner.PREFER, fn, f"{pinned_dir}/manifest.json")

    objects = {
        f"{pinned_dir}/current.json": {
            "pipeline_version": "doc-tools@v3",
            "manifest_key": f"{pinned_dir}/doc-tools@v3/manifest.json",
            "updated_at": "2026-09-30T00:00:00+00:00",
        },
        f"{pinned_dir}/doc-tools@v3/manifest.json": {
            "filename": fn,
            "text_location": f"{pinned_dir}/doc-tools@v3/text.json",
        },
        # A second, unpinned copy of the same filename elsewhere — still legacy-shaped —
        # so pick() has a real choice to make and isn't just resolving a singleton list.
        f"{other_dir}/manifest.json": {
            "filename": fn,
            "text_location": f"{other_dir}/text.json",
        },
    }
    c = _FakeS3(objects)
    by_file = runner.find_manifests(c)
    cands = by_file[fn]
    assert len(cands) == 2

    key, m = runner.pick(fn, cands)
    assert key == f"{pinned_dir}/doc-tools@v3/manifest.json", (
        "the PREFER pin must still win after the pinned directory was reprocessed under "
        "the versioned layout, not fall through to the lexical-first candidate"
    )


def test_legacy_fallback_reproduces_the_real_sandbox_corpus_shape(runner):
    """Exercises the no-current.json path against a fixture shaped like the real sandbox
    corpus, not just synthetic notices.

    All 9 real notices in sandbox MinIO sit at unversioned (legacy) paths today — none
    have been reprocessed under the versioned layout, so none have a current.json. One of
    them, Diodes_PCN_2683_Rev1_EOL.pdf, has THREE legacy manifest copies (diodes_2683,
    diodes_bbox, diodes_tier1 — byte-identical source PDF, non-interchangeable manifests,
    see the PREFER comment in pcn_corpus_run.py), and a real corpus fire's log line reads
    "(3 manifest(s), using sustainment/inbound/diodes_bbox/generated/
    Diodes_PCN_2683_Rev1_EOL_pdf/manifest.json)". This fixture reproduces that: the
    no-current.json path must still surface all 3 candidates for that filename, pick()
    must still resolve to exactly the diodes_bbox key, and the corpus must still find all
    9 filenames from TARGETS — not 8, not 9-with-one-silently-wrong.

    Built from the module's own TARGETS/PREFER rather than hand-duplicated constants, so
    this test tracks the real corpus list instead of drifting from it.
    """
    objects = {}

    def add_legacy(doc_dir, filename):
        objects[f"{doc_dir}/manifest.json"] = {
            "filename": filename,
            "text_location": f"{doc_dir}/text.json",
        }

    # The three PREFER-pinned notices: each notice's PINNED copy, reconstructed from the
    # module's own PREFER dict (so this test can't silently drift from the real pin).
    pinned_dirs = {}
    for fn, want_key in runner.PREFER.items():
        assert want_key.endswith("/manifest.json")
        pinned_dirs[fn] = want_key[: -len("/manifest.json")]
        add_legacy(pinned_dirs[fn], fn)

    # Diodes_PCN_2683_Rev1_EOL.pdf additionally has two MORE legacy copies alongside its
    # pinned one — reproducing the real "3 manifest(s)" shape from the fire log.
    diodes_fn = "Diodes_PCN_2683_Rev1_EOL.pdf"
    diodes_pinned_dir = pinned_dirs[diodes_fn]
    assert "diodes_bbox" in diodes_pinned_dir
    for alt in ("diodes_2683", "diodes_tier1"):
        add_legacy(diodes_pinned_dir.replace("diodes_bbox", alt), diodes_fn)

    # ADI's and onsemi's pinned notices also have a second (unpinned) legacy copy each, so
    # pick() has a real choice to make for them too, not just a singleton list.
    add_legacy(pinned_dirs["ADI_PDN_23_0120.pdf"].replace("adi_run3", "adi_run1"),
               "ADI_PDN_23_0120.pdf")
    add_legacy(pinned_dirs["onsemi_Generic_IPCN25300X.pdf"].replace("onsemi_truthkey", "onsemi_run1"),
               "onsemi_Generic_IPCN25300X.pdf")

    # Every other TARGETS filename: one ordinary, unpinned legacy copy.
    for t in runner.TARGETS:
        fn = t["file"]
        if fn in runner.PREFER:
            continue
        base_name = fn.replace(".", "_")
        add_legacy(f"sustainment/inbound/{base_name}_only/generated/{base_name}", fn)

    c = _FakeS3(objects)
    by_file = runner.find_manifests(c)

    target_filenames = {t["file"] for t in runner.TARGETS}
    assert set(by_file.keys()) == target_filenames, (
        f"expected to find exactly the {len(target_filenames)} real corpus notices; "
        f"got {sorted(by_file.keys())}"
    )

    diodes_cands = by_file[diodes_fn]
    assert len(diodes_cands) == 3, f"expected 3 legacy manifests for {diodes_fn}, got {len(diodes_cands)}"
    key, _m = runner.pick(diodes_fn, diodes_cands)
    assert key == runner.PREFER[diodes_fn] == (
        "sustainment/inbound/diodes_bbox/generated/Diodes_PCN_2683_Rev1_EOL_pdf/manifest.json"
    ), "the no-current.json path must resolve the exact key the real fire log reported"

    for fn in ("ADI_PDN_23_0120.pdf", "onsemi_Generic_IPCN25300X.pdf"):
        key, _m = runner.pick(fn, by_file[fn])
        assert key == runner.PREFER[fn]
