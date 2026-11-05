"""The shape tokeniser: draws a replacement with the SHAPE of an original and
nothing else of it.

Design section 2 of the 2026-10-22 batch-fixture scrubber design. The salt is
bytes the caller holds; it is never logged, never returned, never written to the
ledger -- ``ScrubRun.salt_ref`` carries the NAME of the secret, not the secret.

WHAT EACH RULE IS FOR
---------------------
* *Shape-for-shape (2.1 / 2.2b).* Uppercase -> uppercase, lowercase ->
  lowercase, digit -> digit, anything else LITERAL. A shape-unequal replacement
  means the fixture tests the scrubber, not the extractor, so the shape is
  asserted before a draw is returned.
* *Deterministic and injective within a batch (2.2a).* The draw is seeded
  ``HMAC-SHA256(salt, original + "#" + attempt)`` and consumed as a byte stream,
  one byte per position. The same original always draws the same replacement,
  and a notice that names a part in prose and again in a table gets one
  replacement in both places.
* *No structure beyond the shape (2.3).* Each position is drawn independently
  from its own byte. Character repeats (``FK2500037``'s 00), ascending runs and
  shared prefixes (``FK25...`` across a family) do not survive, because a fixture
  that kept them would teach the extractor structure a real, scrubbed part
  number would not have.
* *Reserved space (2.4 option i).* The first uppercase run of a replacement is
  drawn only from ``RESERVED_LEADING_UPPER``, a leading-letter space no
  vendor's catalogue is being claimed to use. This is how a scrubbed fixture is
  kept from naming a REAL part by chance.
* *Redraw on collision (2.4 option ii, the assertion on top).* The reserved
  space is a convention; the redraw is the check. ``forbidden`` is every known
  real MPN the caller supplies, the originals, and the replacements already
  drawn. A hit retries with ``attempt + 1``; after ``MAX_ATTEMPTS`` the draw
  RAISES rather than return a colliding replacement.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Dict

from doc_tools.scrub.ledger import shape_of, shapes_equal

#: The only letters a replacement's leading uppercase run may use.
RESERVED_LEADING_UPPER: tuple = ("Q", "X", "Z")

MAX_ATTEMPTS = 64

_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_DIGITS = "0123456789"

RESERVED_SPACE_DRAWN = "leading uppercase from {Q,X,Z}"
RESERVED_SPACE_NONE = ("none: no leading uppercase run; collision_check "
                       "carries this one alone")


class CollisionExhausted(RuntimeError):
    """No non-colliding replacement was found in ``MAX_ATTEMPTS`` draws."""


@dataclass(frozen=True)
class Draw:
    replacement: str
    reserved_space: str  # what was reserved, or why nothing was
    redraws: int


def _first_alnum_is_upper(text: str) -> bool:
    for ch in text:
        if ch.isupper():
            return True
        if ch.islower() or ch.isdigit():
            return False
    return False


class Drawer:
    def __init__(self, salt: bytes, *, forbidden: frozenset = frozenset()) -> None:
        if not isinstance(salt, (bytes, bytearray)) or not salt:
            raise ValueError("salt must be non-empty bytes held by the caller")
        # Held privately; never exposed by an attribute, repr or error message.
        self.__salt = bytes(salt)
        self._forbidden = set(forbidden)
        self._cache: Dict[str, Draw] = {}
        self._drawn: set = set()

    def __repr__(self) -> str:  # the salt must not reach a log through repr
        return f"Drawer(drawn={len(self._cache)}, forbidden={len(self._forbidden)})"

    def _stream(self, original: str, attempt: int):
        base = original.encode() + b"#" + str(attempt).encode()
        block = 0
        while True:
            msg = base if block == 0 else base + b"#" + str(block).encode()
            yield from hmac.new(self.__salt, msg, hashlib.sha256).digest()
            block += 1

    def _once(self, original: str, attempt: int) -> str:
        stream = self._stream(original, attempt)
        in_run = _first_alnum_is_upper(original)
        seen = False
        out = []
        for ch in original:
            b = next(stream)
            if ch.isupper():
                if in_run:
                    out.append(RESERVED_LEADING_UPPER[b % len(RESERVED_LEADING_UPPER)])
                    seen = True
                else:
                    out.append(_UPPER[b % 26])
            elif ch.islower():
                in_run = False
                out.append(_LOWER[b % 26])
            elif ch.isdigit():
                in_run = False
                out.append(_DIGITS[b % 10])
            else:
                # Literal. Once the run has started, a separator ends it.
                out.append(ch)
                if seen:
                    in_run = False
        return "".join(out)

    def draw(self, original: str) -> Draw:
        if original in self._cache:
            return self._cache[original]
        shape = shape_of(original)
        reserved = (RESERVED_SPACE_DRAWN if _first_alnum_is_upper(original)
                    else RESERVED_SPACE_NONE)
        for attempt in range(MAX_ATTEMPTS):
            cand = self._once(original, attempt)
            if not shapes_equal(shape, cand):
                raise AssertionError("drawn replacement lost its shape")
            if (cand == original or cand in self._forbidden
                    or cand in self._drawn):
                continue
            result = Draw(replacement=cand, reserved_space=reserved,
                          redraws=attempt)
            self._cache[original] = result
            self._drawn.add(cand)
            return result
        raise CollisionExhausted(
            f"no non-colliding replacement for shape {shape!r} in "
            f"{MAX_ATTEMPTS} attempts; the reserved space is too small for "
            f"this shape or the forbidden set is saturated")
