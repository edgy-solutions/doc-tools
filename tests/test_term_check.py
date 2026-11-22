"""The term check must exit non-zero when it finds a hit, and must not reprint a host.

`exiting zero with hits is a fault` -- the architect, 2026-11-19. The fault is easy
to reintroduce: the hand-run form of this check was three greps piped to `wc -l`,
and a pipeline to `wc -l` exits 0 whether or not it matched. These tests pin the
exit code, not the message.

The script is run as a subprocess through `sys.executable` rather than imported, so
the test passes under this repo's venv on Windows and under CI's interpreter on
Linux without either being named here.
"""
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "term_check.py"

CO_AUTHOR = "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
GENERATED = "\U0001f916 Generated with [Claude Code](https://claude.com/claude-code)"


def run(*args):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_a_clean_record_tree_exits_zero(tmp_path):
    write(tmp_path, "r.md", "# A record\n\nIt cites `module.py:12` and a rate of 512/512.\n")
    r = run(str(tmp_path))
    assert r.returncode == 0, r.stdout


def test_an_ipv4_literal_exits_one(tmp_path):
    write(tmp_path, "r.md", "# A record\n\nThe header host is 203.0.113.7 today.\n")
    r = run(str(tmp_path))
    assert r.returncode == 1, r.stdout
    assert "ipv4" in r.stdout


def test_a_hard_hit_is_located_but_never_reprinted(tmp_path):
    write(tmp_path, "r.md", "# A record\n\nThe header host is 203.0.113.7 today.\n")
    r = run(str(tmp_path))
    assert "203.0.113.7" not in r.stdout, "the check must not be what leaks the host"
    assert "r.md:3:" in r.stdout, "it must still say where to look"
    assert "sha256:" in r.stdout


def test_an_internal_suffix_exits_one(tmp_path):
    write(tmp_path, "r.md", "# A record\n\nIt resolves at the broker.svc name.\n")
    r = run(str(tmp_path))
    assert r.returncode == 1, r.stdout
    assert "internal-suffix" in r.stdout


def test_a_domain_shaped_token_alone_exits_two(tmp_path):
    write(tmp_path, "r.md", "# A record\n\nThe kit lives at github.com/owner/arch-kit.\n")
    r = run(str(tmp_path))
    assert r.returncode == 2, r.stdout
    assert "github.com" in r.stdout, "a domain-shaped token is printed, so it can be judged"


def test_a_hard_hit_outranks_a_domain_shaped_one(tmp_path):
    write(tmp_path, "r.md", "# A record\n\nSee github.com/owner/x and 203.0.113.7.\n")
    r = run(str(tmp_path))
    assert r.returncode == 1, r.stdout


def test_the_two_attribution_lines_are_allowed_in_a_commit_message(tmp_path):
    msg = write(tmp_path, "msg.txt", "docs(arch): a change\n\nA body.\n\n%s\n%s\n" % (CO_AUTHOR, GENERATED))
    r = run("--text-file", str(msg))
    assert r.returncode == 0, r.stdout


def test_the_attribution_lines_are_not_allowed_in_a_record(tmp_path):
    write(tmp_path, "r.md", "# A record\n\n%s\n" % GENERATED)
    r = run(str(tmp_path))
    assert r.returncode == 2, r.stdout


def test_the_allowance_is_the_whole_line_not_a_substring(tmp_path):
    msg = write(tmp_path, "msg.txt", "%s and also see evil.com\n" % GENERATED)
    r = run("--text-file", str(msg))
    assert r.returncode == 2, r.stdout


def test_a_commit_message_with_another_domain_still_exits_two(tmp_path):
    msg = write(tmp_path, "msg.txt", "docs: a change\n\nIt mentions example.com.\n\n%s\n" % CO_AUTHOR)
    r = run("--text-file", str(msg))
    assert r.returncode == 2, r.stdout


def test_no_file_to_check_exits_three(tmp_path):
    r = run(str(tmp_path / "absent"))
    assert r.returncode == 3, r.stdout
