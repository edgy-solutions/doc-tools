"""Read an extractor element-text dump into scrubber ``Block`` s.

The dump format is the one committed at
``tests/fixtures/sustainment/diodes_rev1_eol_text.txt``: ``--- Page N ---``
dividers and one ``[ElementKind] text`` per line.

The point is a REAL document, not a perfect region map, so the mapping is kept
deliberately simple:

* ``[Table]``                -> ``table_cell`` (row 0, col = the table element's
  index on its page), class ``MPN_AFFECTED``;
* ``[FigureCaption]`` / ``[Title]`` -> ``caption``, no class;
* everything else            -> ``body_text``, no class.

A candidate in a classless block is substituted only if it equals an original
classified elsewhere (the scrubber's load-bearing rule), so the form number and
footer in the body text stay unscrubbed and are reported as ``unclassified``.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from doc_tools.scrub.ledger import SubstitutionClass
from doc_tools.scrub.scrubber import Block


_PAGE = re.compile(r"^--- Page (\d+) ---\s*$")
_ELEMENT = re.compile(r"^\[(\w+)\] ?(.*)$")


def read_blocks(path) -> Tuple[Block, ...]:
    blocks: List[Block] = []
    page = 1
    table_index = 0
    with open(path, encoding="utf-8") as f:
        for line in f.read().splitlines():
            m = _PAGE.match(line)
            if m:
                page = int(m.group(1))
                table_index = 0
                continue
            m = _ELEMENT.match(line)
            if not m:
                continue
            kind, text = m.group(1), m.group(2)
            if kind == "Table":
                blocks.append(Block(text, page, "table_cell", row=0,
                                    col=table_index,
                                    scrub_class=SubstitutionClass.MPN_AFFECTED))
                table_index += 1
            elif kind in ("FigureCaption", "Title"):
                blocks.append(Block(text, page, "caption"))
            else:
                blocks.append(Block(text, page, "body_text"))
    return tuple(blocks)
