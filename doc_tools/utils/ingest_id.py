"""The ONE spelling of an `ingest_id` doc-tools is allowed to emit.

ADR-0041 ruling (architect, 2026-10-02): *"ingest_id is the SDK shape
(sha256:<hex>) everywhere, uuid form is a defect."* Applied here, with one
premise corrected — see WHERE THE RULE ACTUALLY LIVES below.

WHY THIS EXISTS AT ALL — the two-shape defect it closes
-------------------------------------------------------
Before this module, `manifest["ingest_id"]` could hold two different strings
for the same concept:

  * Lane 1's sidecar supplies ``sha256:<64 lowercase hex>``.
  * doc-tools' own fallback minted ``hashlib.sha256(...).hexdigest()`` — the
    bare 64 hex, **no prefix**.

`ingest_id` is the join key: Lane 1's promotion store deletes "everything
whose block carries the id" by scoping an `EdgeIdentityFilter` to
``key=ingest_id`` alone (see the SDK's `provenance.py` docstring, section
"ingest_id, ADDED 2026-09-30"). Two spellings of one document's id means the
cleanup sweep matches one set of triples and misses the other, and
`invincible-agent/src/iagent/promotion.py`'s payload guard refuses the
bare-hex spelling outright — so a doc-tools-minted ingest would have been
refused promotion for a spelling mismatch. That refusal path is the exact
failure `invincible-agent/src/iagent/ingest_status.py` names in its own
module docstring.

WHERE THE RULE ACTUALLY LIVES (the ruling's premise, corrected)
---------------------------------------------------------------
The ruling attributes the shape to the SDK. **It is not an SDK contract.**
Measured against `iagent-mesh-sdk` at `c670fa0`:

  * `iagent_mesh/provenance.py:158` declares ``ingest_id: Optional[str] =
    None`` with **no validator** — its `field_validator` covers only
    `authoritative_source`, `as_of`, `ingested_at`, `ingest_run`, `standing`.
  * The literal ``sha256:`` appears **nowhere** in the SDK.

The authority is Lane 1:

  * `invincible-agent/src/iagent/promotion.py:65` —
    ``INGEST_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")``
  * `promotion.py:136` — ``ingest_id_for(data) = "sha256:" + sha256(data).hexdigest()``
  * `ingest_status.py:166` — `update_status` **already refuses** a value that
    does not match it.

Consequence for maintenance: the SDK will NOT catch a drift between these two
repos, because the SDK does not know the shape. `INGEST_ID_RE` below is
therefore a MIRROR of a constant doc-tools cannot import (it lives in
`invincible-agent`, not in the published `iagent_mesh` package), which is a
named exception to `utils/dagster_resources.py`'s own "import the vocabulary,
never mirror it" rule — that rule is satisfiable for `INGEST_STAGES`, which IS
in the SDK, and is not satisfiable for this one. If Lane 1 narrows its regex,
this mirror must follow; a test pins the pattern string so the divergence is
at least visible in a diff.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

__all__ = [
    "INGEST_ID_RE",
    "IngestIdShapeError",
    "mint_ingest_id",
    "canonical_ingest_id",
]

#: MIRROR of `invincible-agent/src/iagent/promotion.py:65`. Not importable —
#: it is not in the `iagent_mesh` package. See the module docstring.
INGEST_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: A bare sha256 hexdigest — what doc-tools' own fallback used to mint. This
#: is COERCIBLE (it is the same digest, just unprefixed), unlike a uuid.
_BARE_SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


class IngestIdShapeError(ValueError):
    """An `ingest_id` that is neither canonical nor losslessly coercible.

    Raised rather than defaulted: an `ingest_id` is a join key into another
    service's store, so a guessed or re-derived one points at nothing. A uuid
    is the named case — it is not a digest of anything, so there is no
    conversion to the canonical form, only a substitution.
    """


def mint_ingest_id(data: bytes) -> str:
    """Mint the canonical `ingest_id` for `data`'s bytes.

    Byte-for-byte the same derivation as
    `invincible-agent/src/iagent/promotion.py:136`'s ``ingest_id_for`` — so a
    doc-tools-minted id for a document equals the id Lane 1 would mint for the
    same bytes, which is the only reason the two can be joined at all.
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_ingest_id(value: Optional[str], *, where: str) -> str:
    """Return `value` in the canonical spelling, or raise.

    `where` names the producer in the error/warning text — the point of this
    function is to make a defective producer identifiable, so it is required.

    Three outcomes, deliberately not two:

    * already canonical -> returned unchanged, silently.
    * bare 64-hex -> prefixed and lowercased, with a WARNING. The value is
      recoverable, but the producer emitting it is itself the defect this
      module closes, so it is never coerced quietly.
    * anything else (uuid, truncated hex, empty, None) -> `IngestIdShapeError`.
    """
    if value is None or not isinstance(value, str) or not value.strip():
        raise IngestIdShapeError(
            f"{where}: ingest_id is {value!r}. It is the join key into Lane 1's "
            f"ingest_status_projection / promotion store, so there is nothing "
            f"to substitute — a minted replacement would name a row that does "
            f"not exist. Expected {INGEST_ID_RE.pattern!r}."
        )

    candidate = value.strip()
    if INGEST_ID_RE.match(candidate):
        return candidate

    if _BARE_SHA256_RE.match(candidate):
        coerced = "sha256:" + candidate.lower()
        logging.getLogger(__name__).warning(
            "%s: ingest_id %r is a BARE sha256 hexdigest with no 'sha256:' "
            "prefix — coerced to %r. The value is recoverable, but the "
            "producer is emitting a spelling "
            "invincible-agent/src/iagent/promotion.py's INGEST_ID_RE refuses, "
            "which is how an ingest gets refused promotion for a spelling "
            "mismatch. Fix the producer.",
            where, candidate, coerced,
        )
        return coerced

    raise IngestIdShapeError(
        f"{where}: ingest_id {candidate!r} does not match "
        f"{INGEST_ID_RE.pattern!r} and is not a bare sha256 hexdigest that "
        f"could be prefixed. A uuid is the named case in the 2026-10-02 "
        f"ruling: it is not a digest of the document's bytes, so it cannot be "
        f"converted into the canonical form — only substituted for it, which "
        f"breaks the join. Mint with mint_ingest_id(file_bytes) instead."
    )
