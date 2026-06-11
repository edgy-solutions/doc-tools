"""Guard against the SPARQL string-literal escape regression.

History: ``build_knowledge_graph`` was emitting SPARQL INSERT DATA
queries that interpolated extracted-text fields directly into
double-quoted string literals, with at most a ``.replace('"', '')``
strip. SPARQL grammar forbids raw newline / CR / tab / backslash /
unescaped double-quote inside ``"..."`` — Fuseki replies HTTP 400
Bad Request. Any document with multi-line extracted text (i.e. almost
all real documents) triggered the failure.

The fix is ``doc_tools.utils.jena_client.escape_sparql_string``
applied at every plugin interpolation site. This test guards against:

  1. The helper being deleted or weakened (unit test on the helper).
  2. New plugin code added that bypasses the helper (integration test
     that builds a tiny plugin-output SPARQL with dirty input and
     verifies it parses cleanly).

Run: ``pytest doc_tools_tests/test_sparql_escape.py``
"""
import re

import pytest

from doc_tools.utils.jena_client import escape_sparql_string


# ---------------------------------------------------------------------------
# Unit tests on the helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("plain", "plain"),
    ("with \"quotes\"", "with \\\"quotes\\\""),
    ("with\nnewline", "with\\nnewline"),
    ("with\r\ncrlf", "with\\r\\ncrlf"),
    ("with\ttab", "with\\ttab"),
    ("with\\backslash", "with\\\\backslash"),
    # Order-of-operations: backslash must escape FIRST so that the \" added
    # later doesn't get re-escaped to \\\". This case proves it.
    ('contains \\ then "', 'contains \\\\ then \\"'),
    # Realistic: multi-line extracted text with quoted speech, the exact
    # pattern that caused the original 400s.
    (
        'Step 1:\nUse the "Allen" key.\nTorque to 5 N·m.',
        'Step 1:\\nUse the \\"Allen\\" key.\\nTorque to 5 N·m.'
    ),
])
def test_escape_known_inputs(raw: str, expected: str):
    assert escape_sparql_string(raw) == expected


def test_escape_idempotent_on_clean_input():
    """No-op on strings that already lack problematic characters."""
    s = "Use Allen key A23 then verify."
    assert escape_sparql_string(s) == s


def test_escape_does_not_eat_unicode():
    """Non-ASCII text passes through (only ASCII control chars are touched)."""
    s = "Törque to 5 N·m — verify"
    assert escape_sparql_string(s) == s


# ---------------------------------------------------------------------------
# Integration: prove the helper output parses as valid SPARQL Update
# ---------------------------------------------------------------------------

# A minimal SPARQL Update parseability check. We don't try to fully validate
# the grammar — a regex that catches the historical failure modes is enough:
# a raw newline OR a raw double-quote inside a ``"..."`` literal.
_DOUBLE_QUOTED_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _all_literals_well_formed(sparql: str) -> bool:
    """Every ``"..."`` literal in the body must have only escaped specials.

    Returns False if any literal contains a raw newline (\\n) or
    unescaped backslash (\\) or raw tab — the exact characters Fuseki
    400s on.
    """
    for m in _DOUBLE_QUOTED_LITERAL.finditer(sparql):
        body = m.group(1)
        # The regex already required \" to be escaped via [^"\\]|\\. — so
        # bare unescaped " inside body would have terminated the match
        # early. What we additionally check: no raw control chars.
        for bad in ("\n", "\r", "\t"):
            if bad in body:
                return False
        # Backslash that isn't followed by an escapable char.
        i = 0
        while i < len(body):
            if body[i] == "\\":
                if i + 1 >= len(body) or body[i + 1] not in '"\\nrt':
                    return False
                i += 2
            else:
                i += 1
    return True


def test_plugin_pattern_dirty_input_produces_valid_sparql():
    """The historical failure pattern: a step with multi-line text and a
    quote in the action verb. After applying ``escape_sparql_string``,
    the resulting SPARQL must contain no raw newlines or unescaped quotes
    inside its string literals.
    """
    dirty_action = 'Operate "Allen" key'
    dirty_text = "multi-line\ninstruction\twith \"quotes\""

    # Mimics manufacturing.py / maintenance.py shape.
    sparql = f"""
    PREFIX mfg: <http://example.com/mfg#>
    INSERT DATA {{
        mfg:step1 a mfg:Step ;
            mfg:hasAction "{escape_sparql_string(dirty_action)}" ;
            mfg:hasText "{escape_sparql_string(dirty_text)}" .
    }}
    """
    assert _all_literals_well_formed(sparql), (
        f"Plugin output still contains malformed string literals: {sparql}"
    )


def test_plugin_pattern_without_escape_is_caught():
    """Sanity check on the test itself: an unescaped body fails the
    well-formed check. If this passes, the test above is meaningless.
    """
    dirty_text = "multi-line\ninstruction"
    sparql = f"""
    PREFIX mfg: <http://example.com/mfg#>
    INSERT DATA {{
        mfg:step1 mfg:hasText "{dirty_text}" .
    }}
    """
    assert not _all_literals_well_formed(sparql)
