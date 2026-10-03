"""The dated markdown report is an archive, so its name must identify a RUN.

This exists because the archive name used to be `report-{generated_at[:10]}.md`
-- the UTC date and nothing else. Two runs on one day therefore wrote the same
path, and the second silently destroyed the first. Nothing surfaced it: git
records it as an ordinary file modification, the publisher commits whatever is
on disk, and `latest.json` is *supposed* to be overwritten, so the one file that
could have shown the loss looked correct.

It was found on 2026-10-01, when `main` turned out to be carrying
`report-2026-10-01.md` and `report-2026-10-01-rereduced.md` -- two different
runs of the same day, the second surviving only because a human renamed it --
and that night's nightly then overwrote the dated file a third time on the
publish branch.

The test is on the naming helper rather than on `main()` because the invariant
IS the name: distinct runs must not collide, and runs must still sort by time.
"""

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    # pcn_corpus_gate imports its sibling pcn_header_agreement by plain module
    # name, so scripts/ has to be importable.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("pcn_corpus_gate")


def test_two_runs_on_the_same_day_do_not_share_a_filename():
    # The exact pair that collided: the 03:05Z re-reduction and the 06:26Z
    # nightly, both on 2026-10-01.
    first = gate.dated_report_name("2026-10-01T03:05:34Z")
    second = gate.dated_report_name("2026-10-01T06:26:31Z")
    assert first != second, (
        "same-day runs still collide, which is the bug this guards: "
        f"{first!r} == {second!r}"
    )


def test_the_name_carries_no_character_illegal_in_a_filename():
    # Colons are legal in an ISO timestamp and illegal in a Windows filename,
    # and the gate's own report dir is checked out on Windows by this repo's
    # developers. A name that cannot be written is not an archive.
    name = gate.dated_report_name("2026-10-01T06:26:31Z")
    for bad in ':*?"<>|':
        assert bad not in name, f"{bad!r} is not writable as a filename: {name!r}"


def test_names_sort_chronologically_as_plain_text():
    # `pcn_gate_publish.py` presents the archive through `sorted(glob(...))`,
    # so lexicographic order has to be time order or the listing misleads.
    stamps = [
        "2026-09-30T23:59:59Z",
        "2026-10-01T03:05:34Z",
        "2026-10-01T06:26:31Z",
        "2026-10-02T00:00:00Z",
    ]
    names = [gate.dated_report_name(s) for s in stamps]
    assert names == sorted(names)


def test_the_publisher_glob_still_matches():
    # The fix lengthens the name; the publisher collects reports with a
    # `report-*.md` glob and must not need a matching change.
    name = gate.dated_report_name("2026-10-01T06:26:31Z")
    assert name.startswith("report-") and name.endswith(".md")


def test_the_run_timestamp_is_recoverable_from_the_name():
    # The point of the longer name is that a reader can tell WHICH run a file
    # came from without opening it.
    assert gate.dated_report_name("2026-10-01T06:26:31Z") == "report-2026-10-01T062631Z.md"
