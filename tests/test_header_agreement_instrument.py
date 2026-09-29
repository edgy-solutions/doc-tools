"""Tests for the header-agreement instrument (`scripts/pcn_header_agreement.py`).

Default mode only — no S3, no network, no LLM. `--written` mode needs live MinIO
and a `doc_tools` import and is exercised only by hand against real corpus fires
(see the script's own docstring); this file proves the log-parsing and
agreement logic that both modes share.

Imported by path rather than as a package, following `tests/test_pcn_score.py`:
`scripts/` is not importable and an `__init__.py` there would make a
measurement harness look like library code.
"""
import importlib.util
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hdr = _load("pcn_header_agreement")

MARKER = "---Parsed Response (class NoticeHeader)---"

BASE_HEADER = {
    "doc_id": "DOC-1",
    "doc_type": "PCN",
    "mfr": "Acme Corp",
    "mfr_source": "Acme Corp letterhead",
    "pub_date": "2024-01-01",
    "pub_date_source": "Date: 2024-01-01",
    "doc_level_ltb_date": None,
    "doc_level_ltb_date_source": None,
}


def _indented_json(d):
    """Render `d` the way the real BAML log indents a parsed block: every line
    of the pretty-printed JSON prefixed with two spaces, first line included."""
    return "\n".join("  " + line for line in json.dumps(d, indent=2).splitlines())


def _notice_block(name, header, progress_line="    parts=5/5  elapsed=1.0s"):
    """One `--- name.pdf ...` notice section carrying a single parsed block,
    in the real log shape."""
    return (
        f"--- {name}  (1 manifest(s), using some/key)\n"
        f"{MARKER}\n"
        f"{_indented_json(header)}\n"
        f"{progress_line}\n"
    )


def _write_log(tmp_path, filename, text):
    p = tmp_path / filename
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_two_agreeing_logs_exit_zero(tmp_path, capsys):
    log1 = _write_log(tmp_path, "fire1.log", _notice_block("A.pdf", BASE_HEADER))
    log2 = _write_log(tmp_path, "fire2.log", _notice_block("A.pdf", BASE_HEADER))

    rc = hdr.main([log1, log2])

    out = capsys.readouterr().out
    assert rc == 0
    assert "A.pdf" in out
    assert "DISAGREE" not in out


def test_two_logs_disagreeing_on_mfr_exit_one_and_names_field(tmp_path, capsys):
    header2 = dict(BASE_HEADER, mfr="Other Corp", mfr_source="Other Corp letterhead")
    log1 = _write_log(tmp_path, "fire1.log", _notice_block("A.pdf", BASE_HEADER))
    log2 = _write_log(tmp_path, "fire2.log", _notice_block("A.pdf", header2))

    rc = hdr.main([log1, log2])

    out = capsys.readouterr().out
    assert rc == 1
    assert "DISAGREE" in out
    assert "mfr" in out
    assert "Acme Corp" in out and "Other Corp" in out


def test_a_notice_one_fire_never_measured_FAILS_rather_than_passing_quietly(tmp_path, capsys):
    """A notice present in one fire and absent from another is a gate FAILURE.

    It cannot be said to agree — nothing was measured to agree with — and the usual
    cause is a fire that died partway through the corpus, which is the last thing to
    wave through on the strength of the notices that did survive.
    """
    log1 = _write_log(
        tmp_path, "fire1.log",
        _notice_block("A.pdf", BASE_HEADER) + _notice_block("B.pdf", BASE_HEADER))
    log2 = _write_log(tmp_path, "fire2.log", _notice_block("A.pdf", BASE_HEADER))

    rc = hdr.main([log1, log2])  # must not raise

    out = capsys.readouterr().out
    assert rc == 1
    assert "B.pdf" in out
    assert "ABSENT" in out
    assert "fire2.log" in out  # names WHICH fire never measured it


def test_fewer_than_two_logs_exit_two(tmp_path, capsys):
    log1 = _write_log(tmp_path, "fire1.log", _notice_block("A.pdf", BASE_HEADER))

    rc = hdr.main([log1])

    assert rc == 2


def test_last_parsed_block_wins(tmp_path, capsys):
    first_block = dict(BASE_HEADER, doc_id="FIRST")
    last_block = dict(BASE_HEADER, doc_id="LAST")
    log_text = _notice_block("A.pdf", first_block) + _notice_block("A.pdf", last_block)
    log1 = _write_log(tmp_path, "fire1.log", log_text)
    # The other fire only ever saw the value that should win.
    log2 = _write_log(tmp_path, "fire2.log", _notice_block("A.pdf", last_block))

    rc = hdr.main([log1, log2])

    out = capsys.readouterr().out
    assert rc == 0, out
    assert "DISAGREE" not in out


def test_headers_from_log_keeps_last_block_directly(tmp_path):
    first_block = dict(BASE_HEADER, doc_id="FIRST")
    last_block = dict(BASE_HEADER, doc_id="LAST")
    log_text = _notice_block("A.pdf", first_block) + _notice_block("A.pdf", last_block)
    log1 = _write_log(tmp_path, "fire1.log", log_text)

    parsed = hdr.headers_from_log(log1)

    assert parsed["A.pdf"]["doc_id"] == "LAST"


# --- the bounded-region / interleaved-log fix --------------------------------
#
# All four tests below are built on ONE real observation, not a hypothetical:
# on fire 1 of the 2026-09-28 three-fire gate at pin 7104b595, BAML's async
# logging spliced another function's line into the middle of the TYC block's
# `summary` value:
#
#     "summary": "... parts due2026-09-29T03:13:52.328 [BAML INFO] Function TranscribePage:
#
# so that block's JSON string never closed. The brace matcher then ran to
# end-of-file and the loop resumed there, so the 8 notices AFTER TYC were never
# seen at all and were reported as ABSENT. Two real TYC differences arrived
# dressed as 16 field disagreements, and the gate failed for a logging artifact.

INTERLEAVED = (
    '2026-09-29T03:13:52.328 [BAML INFO] Function TranscribePage:'
    ' Prompt (truncated)'
)


def _corrupt_block(name, header, tail_field="summary"):
    """A notice block whose LAST field is cut mid-string by an interleaved BAML
    log line, exactly as observed. Every field before `tail_field` is intact and
    the closing brace never arrives."""
    body = _indented_json(header).rstrip()
    assert body.endswith("}")
    body = body[: body.rindex("}")].rstrip().rstrip(",")
    return (
        f"--- {name}  (1 manifest(s), using some/key)\n"
        f"{MARKER}\n"
        f"{body},\n"
        f'  "{tail_field}": "five connector parts due{INTERLEAVED}\n'
    )


def test_a_corrupt_block_does_not_swallow_the_notices_after_it(tmp_path):
    """THE REGRESSION. The corrupt block is first; the two good notices after it
    must still be measured. Before the fix this returned 1 notice."""
    text = (
        _corrupt_block("TYC.pdf", BASE_HEADER)
        + _notice_block("B.pdf", BASE_HEADER)
        + _notice_block("C.pdf", BASE_HEADER)
    )
    log = _write_log(tmp_path, "fire1.log", text)

    got = hdr.headers_from_log(log)

    assert sorted(got) == ["B.pdf", "C.pdf", "TYC.pdf"], (
        "a block that never closes must not consume the rest of the log"
    )
    assert got["B.pdf"] == BASE_HEADER
    assert got["C.pdf"] == BASE_HEADER


def test_scalar_fields_before_the_damage_are_recovered(tmp_path):
    """Recovery is only worth having if it returns the fields the gate compares.
    In THIS block every RAW_FIELD precedes the damage, so every one survives and the
    truncated field itself must not be invented. That is a property of where the
    splice landed, not a general one -- the real fire-1 TYC block lost two fields
    this way, which the NOT-MEASURED tests below pin."""
    log = _write_log(tmp_path, "fire1.log", _corrupt_block("TYC.pdf", BASE_HEADER))

    got = hdr.headers_from_log(log)["TYC.pdf"]

    for field in hdr.RAW_FIELDS:
        assert field in got, f"{field} was readable before the damage but is missing"
        assert got[field] == BASE_HEADER[field]
    assert "summary" not in got, (
        "a value cut mid-string must be absent, never half-recovered"
    )


def test_a_recovered_parse_is_reported_not_silent(tmp_path, capsys):
    """Agreement measured off a damaged log must say so. The verdict may still be
    HELD — the compared fields really did agree — but the reader has to be told
    which block needed recovery, or 'HELD' implies a clean log."""
    hdr.PARSE_RECOVERED.clear()
    good = _notice_block("B.pdf", BASE_HEADER)
    log1 = _write_log(tmp_path, "fire1.log",
                      _corrupt_block("TYC.pdf", BASE_HEADER) + good)
    log2 = _write_log(tmp_path, "fire2.log",
                      _notice_block("TYC.pdf", BASE_HEADER) + good)

    rc = hdr.main([log1, log2])
    out = capsys.readouterr().out

    assert rc == 0, "the compared fields agreed; recovery is not a disagreement"
    assert "PARSER NOTE" in out
    assert "TYC.pdf" in out
    assert "fire1.log" in out, "the note must name WHICH fire's log was damaged"
    hdr.PARSE_RECOVERED.clear()


def test_a_clean_log_parses_byte_identically_to_json_loads(tmp_path):
    """The fix must not change what a healthy log yields. Strict JSON parsing
    stays the path for a block that closes, and no PARSER NOTE is raised."""
    hdr.PARSE_RECOVERED.clear()
    other = dict(BASE_HEADER, doc_id="DOC-2", doc_level_ltb_date="2025-06-30")
    log = _write_log(
        tmp_path, "clean.log",
        _notice_block("A.pdf", BASE_HEADER) + _notice_block("B.pdf", other),
    )

    got = hdr.headers_from_log(log)

    assert got == {"A.pdf": BASE_HEADER, "B.pdf": other}
    assert not hdr.PARSE_RECOVERED, "a clean log must raise no recovery note"


# --- absence is not a value: the NOT_MEASURED sentinel ------------------------
#
# Found by running the bounded parser against the real fire-1 log rather than by
# reasoning about it. Recovery reached `revision` on the TYC block and so lost
# `doc_level_ltb_date` and `doc_level_ltb_date_source`, which are emitted after it.
# `compare` did `v.get(f)` -> None and printed
#
#     doc_level_ltb_date     None | '2024-06-06'
#
# i.e. it asserted fire 1's model emitted null. The log does not support that claim,
# and the row read as instability in the extractor. Damage masquerading as a
# measurement is the same defect class as the one above, one layer in.


def _corrupt_block_losing_tail_fields(name, header, keep_through):
    """A block cut immediately after `keep_through`, so every field declared after it
    in `header` is genuinely absent -- the real fire-1 shape."""
    items = list(header.items())
    cut = [k for k, _ in items].index(keep_through) + 1
    body = _indented_json(dict(items[:cut])).rstrip()
    body = body[: body.rindex("}")].rstrip().rstrip(",")
    return (
        f"--- {name}  (1 manifest(s), using some/key)\n"
        f"{MARKER}\n"
        f"{body},\n"
        f'  "revision": "A{INTERLEAVED}\n'
    )


def test_a_field_lost_to_the_damage_is_not_reported_as_null(tmp_path, capsys):
    """The regression this section exists for: the lost field must compare as
    NOT MEASURED, and must NOT be rendered as a None that differs from the other
    fire's real date."""
    hdr.PARSE_RECOVERED.clear()
    with_date = dict(BASE_HEADER, doc_level_ltb_date="2024-06-06",
                     doc_level_ltb_date_source="06-JUN-2024")
    log1 = _write_log(tmp_path, "fire1.log",
                      _corrupt_block_losing_tail_fields("T.pdf", with_date,
                                                        "pub_date_source"))
    log2 = _write_log(tmp_path, "fire2.log", _notice_block("T.pdf", with_date))

    rc = hdr.main([log1, log2])
    out = capsys.readouterr().out

    assert rc == 1, "a field with no measurement cannot pass a gate"
    assert "NOT MEASURED" in out
    assert "not in evidence, not a value difference" in out
    assert "NOT ESTABLISHED" in out
    assert "None | '2024-06-06'" not in out, (
        "absence must never be rendered as a null the model did not emit"
    )
    hdr.PARSE_RECOVERED.clear()


def test_unmeasured_is_counted_apart_from_disagreement(tmp_path):
    """`compare` returns the two apart so a caller can never total them together.
    Same notice, one genuinely differing field and one unmeasured field."""
    a = dict(BASE_HEADER, doc_level_ltb_date="2024-06-06",
             doc_level_ltb_date_source="06-JUN-2024")
    b = dict(a, mfr="Other Corp")
    fires = [
        ("fire1", {"T.pdf": {k: v for k, v in a.items()
                             if k != "doc_level_ltb_date"}}),
        ("fire2", {"T.pdf": b}),
    ]

    _notices, disagreements, unmeasured = hdr.compare(fires, hdr.RAW_FIELDS)

    assert disagreements == [("T.pdf", "mfr")]
    assert unmeasured == [("T.pdf", "doc_level_ltb_date")]


def test_written_mode_marks_a_written_field_whose_raw_input_was_lost(tmp_path):
    """The sentinel has to survive the trust replay. `refuse_unsourced_header_values`
    runs happily on a dict with the key missing and yields a clean '' -- which would
    look like a measured refusal. Only `doc_type` is exempt, because it is derived
    from the notice's titles rather than from the model's block."""
    class _ShtStub:
        @staticmethod
        def refuse_unsourced_header_values(d, index):
            return []

        @staticmethod
        def doc_type_from_titles(titles):
            return "PCN", "title"

    import sys as _sys
    import types as _types
    pkg = _types.ModuleType("doc_tools")
    utils = _types.ModuleType("doc_tools.utils")
    utils.sustainment_header_trust = _ShtStub
    pkg.utils = utils
    saved = {k: _sys.modules.get(k) for k in ("doc_tools", "doc_tools.utils")}
    _sys.modules["doc_tools"] = pkg
    _sys.modules["doc_tools.utils"] = utils
    try:
        raw_missing = {k: v for k, v in BASE_HEADER.items() if k != "mfr"}
        fires = [("fire1", {"T.pdf": raw_missing}),
                 ("fire2", {"T.pdf": dict(BASE_HEADER)})]
        written, _refusals = hdr.written_from_raw(fires, {"T.pdf": (object(), [])})
    finally:
        for k, v in saved.items():
            if v is None:
                _sys.modules.pop(k, None)
            else:
                _sys.modules[k] = v

    assert written[0][1]["T.pdf"]["mfr"] is hdr.NOT_MEASURED
    assert written[0][1]["T.pdf"]["doc_type"] == "PCN", (
        "doc_type comes from the titles, so log damage cannot unmeasure it"
    )
