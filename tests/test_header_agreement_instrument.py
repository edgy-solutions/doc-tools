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
