"""The scrub allowlist: loads ``registry/scrub_allowlist.yaml`` and finds the spans
of a text that must survive a scrub verbatim.

WHY THIS FILE CARRIES NO VOCABULARY
-----------------------------------
Config names the case, code implements the mechanism. Every allowlisted string
or pattern is named in the YAML; this module only compiles and matches them. A
phrase hard-coded here would be a second list that can drift from the one a
reviewer reads.

THE RULE THIS MODULE SERVES (design section 3.3)
------------------------------------------------
**Allowlist by VOCABULARY, scrub by SHAPE, and let the allowlist win.** The
scrubber asks this module for spans FIRST and substitutes only what survives
them. The tempting simplification -- scrub everything part-shaped -- silently
destroys the column headers, and the headers are what the fixture tests.

DEFECTS EACH GUARD EXISTS FOR
-----------------------------
* *Phrases match on word boundaries.* ``device`` is an affected-column header;
  as a bare substring it would exempt the middle of a part number and leave a
  fragment of it unscrubbed -- a leak the leak test would catch only by luck.
* *Longest match first at each position.* a longer header phrase must win
  over a shorter phrase it contains at the same offset, or the header is split.
* *The date rule is a detector, not a pattern.* There is exactly one date parser
  in the tree (``ltb_candidates.is_entirely_a_date``); the loader rejects a
  config naming any other, because a second parser is the defect that function
  exists to prevent.
* *The ref digests BYTES.* A CRLF rewrite of the file must change the ref
  rather than be invisible -- this repo has already broken a pinned sha by
  writing text.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from doc_tools.scrub.ledger import AllowlistRule

ALLOWLIST_VERSION = 1
_TOP_LEVEL_KEYS = frozenset({"allowlist_version", "rules"})
_SECTION_KEYS = frozenset({"phrases", "patterns", "detector"})
DATE_DETECTOR = "is_entirely_a_date"

#: Longest run of whitespace-separated tokens tried as one date ("22 Dec, 2024"
#: is three; "Monday, December 22, 2024" is four).
_MAX_DATE_TOKENS = 6
_TOKEN = re.compile(r"\S+")
_TRAILERS = ".,;:"


@dataclass(frozen=True)
class AllowlistSpan:
    start: int
    end: int
    rule: AllowlistRule
    text: str  # the source text, verbatim


def _phrase_regex(phrase: str) -> "re.Pattern[str]":
    """A literal phrase as a case-insensitive, word-bounded regex.

    Boundaries are applied only on a side that is alphanumeric, so ``cust ``
    (trailing space, a real extractor header) does not demand a non-alphanumeric
    character AFTER its space.
    """
    trailing_space = phrase != phrase.rstrip()
    core = phrase.rstrip()
    body = r"\s+".join(re.escape(p) for p in re.split(r"\s+", core))
    if trailing_space:
        body += r"\s+"
    pre = r"(?<![A-Za-z0-9])" if core[:1].isalnum() else ""
    post = r"(?![A-Za-z0-9])" if (not trailing_space and core[-1:].isalnum()) else ""
    return re.compile(pre + body + post, re.IGNORECASE)


class Allowlist:
    def __init__(self, ref: str,
                 phrases: Tuple[Tuple[str, AllowlistRule], ...],
                 patterns: Tuple[Tuple[str, AllowlistRule], ...],
                 date_rule: bool) -> None:
        self._ref = ref
        self._phrases = phrases
        self._patterns = patterns
        self._date_rule = date_rule
        self._compiled: List[Tuple["re.Pattern[str]", AllowlistRule]] = (
            [(_phrase_regex(p), r) for p, r in phrases]
            + [(re.compile(p, re.IGNORECASE), r) for p, r in patterns])

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "Allowlist":
        import yaml  # local: keep this module importable without PyYAML

        path = Path(path)
        raw = path.read_bytes()  # BYTES: a CRLF rewrite must change the ref
        data = yaml.safe_load(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: allowlist must be a mapping")
        unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
        if unknown:
            raise ValueError(f"{path}: unknown top-level key(s) {unknown}")
        if data.get("allowlist_version") != ALLOWLIST_VERSION:
            raise ValueError(
                f"{path}: allowlist_version {data.get('allowlist_version')!r} "
                f"is not {ALLOWLIST_VERSION}; a reader that guesses at an "
                f"unknown version is how a config change becomes a silent misread")
        rules = data.get("rules") or {}
        if not isinstance(rules, dict):
            raise ValueError(f"{path}: rules must be a mapping")
        known = {r.value: r for r in AllowlistRule}
        phrases: List[Tuple[str, AllowlistRule]] = []
        patterns: List[Tuple[str, AllowlistRule]] = []
        date_rule = False
        for name, section in rules.items():
            if name not in known:
                raise ValueError(f"{path}: unknown rule {name!r}; known: "
                                 f"{sorted(known)}")
            rule = known[name]
            section = section or {}
            bad = sorted(set(section) - _SECTION_KEYS)
            if bad:
                raise ValueError(f"{path}: rule {name!r} has unknown key(s) {bad}")
            for p in section.get("phrases") or []:
                phrases.append((str(p), rule))
            for p in section.get("patterns") or []:
                re.compile(p)  # a bad pattern fails at load, not at first match
                patterns.append((str(p), rule))
            if "detector" in section:
                if rule is not AllowlistRule.DATE:
                    raise ValueError(f"{path}: only the date rule has a detector")
                if section["detector"] != DATE_DETECTOR:
                    raise ValueError(
                        f"{path}: date.detector must be {DATE_DETECTOR!r}, got "
                        f"{section['detector']!r}; a second date parser is the "
                        f"defect is_entirely_a_date exists to prevent")
                date_rule = True
        digest = hashlib.sha256(raw).hexdigest()[:8]
        return cls(f"{path.as_posix()}@{digest}", tuple(phrases),
                   tuple(patterns), date_rule)

    @property
    def ref(self) -> str:
        """``<path>@<sha256 of the file bytes, 8 hex>`` -- ``ScrubRun.allowlist_ref``."""
        return self._ref

    def phrases(self) -> Tuple[Tuple[str, AllowlistRule], ...]:
        return self._phrases

    # ------------------------------------------------------------------
    def _date_spans(self, text: str) -> List[AllowlistSpan]:
        from doc_tools.utils.ltb_candidates import is_entirely_a_date

        toks = [(m.start(), m.end()) for m in _TOKEN.finditer(text)]
        out: List[AllowlistSpan] = []
        i = 0
        while i < len(toks):
            hit = None
            for width in range(min(_MAX_DATE_TOKENS, len(toks) - i), 0, -1):
                start, end = toks[i][0], toks[i + width - 1][1]
                while end > start and text[end - 1] in _TRAILERS:
                    end -= 1
                if end > start and is_entirely_a_date(text[start:end]):
                    hit = (start, end, width)
                    break
            if hit:
                out.append(AllowlistSpan(hit[0], hit[1], AllowlistRule.DATE,
                                         text[hit[0]:hit[1]]))
                i += hit[2]
            else:
                i += 1
        return out

    def spans(self, text: str, *,
              rules: Optional[frozenset] = None) -> Tuple[AllowlistSpan, ...]:
        """Non-overlapping allowlist spans, longest first at each position.

        ``rules`` restricts which rules are in force: a run whose policy answer
        is SCRUBBED drops ``MANUFACTURER_NAME`` (or ``DATE``) here, which is how
        a policy is HONOURED and not merely recorded.
        """
        def on(rule: AllowlistRule) -> bool:
            return rules is None or rule in rules

        order: Dict[AllowlistRule, int] = {r: i for i, r in enumerate(AllowlistRule)}
        cands: List[AllowlistSpan] = []
        for rx, rule in self._compiled:
            if not on(rule):
                continue
            for m in rx.finditer(text):
                if m.end() > m.start():
                    cands.append(AllowlistSpan(m.start(), m.end(), rule, m.group(0)))
        if self._date_rule and on(AllowlistRule.DATE):
            cands.extend(self._date_spans(text))
        cands.sort(key=lambda s: (s.start, -(s.end - s.start), order[s.rule]))
        chosen: List[AllowlistSpan] = []
        edge = 0
        for s in cands:
            if s.start >= edge:
                chosen.append(s)
                edge = s.end
        return tuple(chosen)
