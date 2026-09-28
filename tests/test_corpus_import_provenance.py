"""The corpus driver must say which `doc_tools` it measured.

On 2026-09-27 two corpus measurements were void because the candidate tree copied into
the pod was never imported: the pod sets `PYTHONPATH=/app`, the driver lives in
`scripts/`, so `sys.path[0]` is `<tree>/scripts` — no `doc_tools` inside it — and `/app`
won. One arm of that failure raised an `AttributeError` for a symbol only the candidate
defined and was caught. The other was a baseline-vs-candidate A/B in which both arms ran
the same `/app` code and agreed with each other, which is the worst possible outcome: a
confident number about a change that never ran.

The guard cannot be a behavioural test — by construction the run behaves perfectly. So it
is asserted on the reported PROVENANCE: the path is computed, printed, and printed again
beside the score, and a mismatch says so in words.

Imported by path rather than as a package, like `test_pcn_score.py`: `scripts/` is not
importable, and adding an `__init__.py` would make a measurement harness look like
library code.
"""
import importlib.util
import os
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def runner():
    pytest.importorskip("boto3", reason="the corpus driver imports boto3 at module level")
    spec = importlib.util.spec_from_file_location("pcn_corpus_run",
                                                  SCRIPTS / "pcn_corpus_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prov(runner, pkg_dir, tree):
    """Provenance as computed for a doc_tools living in `pkg_dir` and a driver in
    `tree/scripts/pcn_corpus_run.py`."""
    return runner.import_provenance(
        os.path.join(pkg_dir, "doc_tools", "__init__.py"),
        os.path.join(tree, "scripts", "pcn_corpus_run.py"))


def test_the_drivers_own_tree_is_recognized(runner, tmp_path):
    p = _prov(runner, str(tmp_path), str(tmp_path))
    assert p["is_driver_tree"] is True, \
        "a run that DID load the tree under test must not warn about it"
    assert "WARNING" not in runner.render_import_provenance(p)


def test_a_foreign_extractor_is_reported_as_foreign(runner, tmp_path):
    """The real case: driver copied to /tmp/cand, extractor imported from /app."""
    p = _prov(runner, "/app", str(tmp_path / "cand"))
    assert p["is_driver_tree"] is False
    out = runner.render_import_provenance(p)
    assert "WARNING" in out, \
        ("a run that measured a DIFFERENT tree than the one it was launched from must say "
         "so — this is the whole defect, and it is invisible in the numbers")
    assert os.path.realpath("/app") in out.replace("\\", "/") or "app" in out


def test_the_warning_names_the_fix(runner, tmp_path):
    """A warning that does not say what to do gets read once and ignored."""
    tree = str(tmp_path / "cand")
    out = runner.render_import_provenance(_prov(runner, "/app", tree))
    assert "PYTHONPATH=" in out, "the warning must carry the relaunch incantation"
    assert os.path.realpath(tree) in out, \
        "the relaunch incantation must name the tree the operator actually wants measured"


def test_both_paths_are_always_reported_even_when_they_agree(runner, tmp_path):
    """Not only on mismatch: a report is copied from a log, and 'no warning' is
    indistinguishable from 'the guard was removed' unless the paths are always there."""
    out = runner.render_import_provenance(_prov(runner, str(tmp_path), str(tmp_path)))
    assert "extractor" in out and "driver" in out


def test_the_provenance_is_printed_beside_the_score(runner):
    """MUTATION CHECK on placement, not on the helper.

    `import_provenance` being correct is worth nothing if `main` prints it only at
    startup: these runs are 20+ minutes and are read by `tail`, so the line that reaches
    a report is the one next to the score. Asserted at the source level because `main`
    cannot be exercised without a pod.
    """
    src = (SCRIPTS / "pcn_corpus_run.py").read_text(encoding="utf-8")
    score_at = src.index("print(pcn_score.render(scored))")
    before = src[:score_at]
    assert "print(render_import_provenance(prov))" in before, \
        "the score must be preceded by the provenance line, or a tailed log omits it"
    assert before.count("print(render_import_provenance(prov))") >= 2, \
        ("expected the provenance printed BOTH at startup and beside the score; a single "
         "print at the top scrolls out of every long run's tail")
