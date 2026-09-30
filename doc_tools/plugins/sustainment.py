"""Sustainment (PCN/PDN) extraction — two-pass, provenance-aware.

Pass 1  ExtractHeader (gpt-oss, text-only)  -> header fields
Pass 2  ExtractParts  (Gemma, multimodal)   -> affected-parts table rows
The final SustainmentNotice is assembled + reconciled HERE in Python.

Design notes:
  * Router: run the vision parts pass only when unstructured detected >=1 Table
    element AND a vision endpoint is configured. No table -> header-only, UNLESS
    the text itself advertises affected parts (an "Affected Parts"-labelled section
    plus an MPN-shaped token — see _has_part_shaped_text) — the PCN24-029 shape,
    a single MPN with no table at all, which used to be lost silently.
  * Per-crop parts calls + dedup: a page-spanning table becomes multiple crops;
    each crop is extracted independently and parts are de-duplicated across
    crops (repeated headers / continued rows). Per-crop also keeps each call's
    OCR+image well inside the vision model's context (e.g. gemma 32k).
  * Models are fully config-driven (BAML clients read LLM_* / VISION_LLM_* env);
    images go as base64 so any OpenAI-compatible backend works — Ollama,
    LiteLLM, vLLM, OpenAI. Nothing is hardcoded.
  * ltb_date ownership (empirical, MinIO corpus scan): per-row primary,
    doc-level fallback (sustainment_merge.reconcile_ltb).
  * Validation -> review lane, never a silent mock. On any failure the node is
    flagged needs_review with reasons; the old MOCK-PDN-123 fabrication is gone.
  * Provenance: every located value carries a verbatim *_source snippet resolved
    to a page + bbox by doc_tools.utils.provenance (Phase 5 review.json).
"""
import io
import os
import re
from typing import List, Optional, Tuple, Any, Dict

from pydantic import BaseModel, Field

from doc_tools.plugins.base import AugmentationPlugin, PromptUnavailableError
from doc_tools.plugins.models import BaseSection, DocumentNode
from doc_tools.utils.jena_client import escape_sparql_string
from doc_tools.utils import provenance
from doc_tools.utils import sustainment_normalize as norm
from doc_tools.utils import sustainment_header_trust as header_trust
from doc_tools.utils import notice_identity
from doc_tools.utils.ltb_candidates import ltb_candidates, render_candidate_block
from doc_tools.utils import table_text_layer as text_layer
from doc_tools.utils import text_layer_health
from doc_tools.utils.sustainment_merge import (
    header_to_dict, part_to_dict, dequote_parts, dedup_parts, reconcile_ltb, clean_replacements,
    build_review_items, validate_count, empty_header,
)

# Telemetry (ADR-0038) — the thin seam lives in doc_tools.telemetry so the mapping
# and the projected-values contract can be unit-tested without the plugin's heavy
# imports (that test is the vocabulary-owner truth check). When the leaf / Langfuse
# is absent these are no-ops, so file-mode keeps its zero-Langfuse-dependency.
from doc_tools.telemetry import traced, set_trace_standard, observed_trace, MAPPING, build_trace_values


# --------------------------------------------------------------------------- #
# Mirror models (carry _source, revision, doc_level_ltb_date + the review lane)
# --------------------------------------------------------------------------- #
class PartImpact(BaseModel):
    affected_mpn: str
    affected_mpn_source: Optional[str] = None
    replacement_mpn: Optional[str] = None
    replacement_mpn_source: Optional[str] = None
    ltb_date: Optional[str] = None
    ltb_date_source: Optional[str] = None


class SustainmentNotice(BaseModel):
    doc_id: str
    doc_type: str
    revision: Optional[str] = None
    pub_date: str
    mfr: str
    # Optional with a None default: an absent parent is the common case, and the notice
    # that forced this field (EOL-36) is itself one where the parent is real but unnamed.
    mfr_parent: Optional[str] = None
    categories: List[str]
    summary: str
    doc_level_ltb_date: Optional[str] = None
    impacted_parts: List[PartImpact]


class SustainmentAugmentation(BaseModel):
    notice: SustainmentNotice
    review: dict = Field(default_factory=dict)          # review.json payload
    needs_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)           # router / coverage instrumentation


def _fetch_image_b64(s3_client, s3_url: str):
    """('image/png'|'image/jpeg', base64str) for an s3://bucket/key crop, or (None, None).

    base64 (not a URL) so the image is portable across Ollama / LiteLLM / vLLM /
    OpenAI — the backend never has to fetch it.
    """
    if not s3_url or not str(s3_url).startswith("s3://"):
        return None, None
    _, _, rest = str(s3_url).partition("s3://")
    bkt, _, key = rest.partition("/")
    try:
        data = s3_client.get_object(Bucket=bkt, Key=key)["Body"].read()
    except Exception as e:  # noqa: BLE001
        print(f"[SustainmentPlugin] failed to fetch crop {s3_url}: {e}")
        return None, None
    import base64
    ext = os.path.splitext(key)[1].lower()
    media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return media, base64.b64encode(data).decode("ascii")


# Output BOUND for the vision pass. MEASURED at both ends (Diodes PCN 2683, 2026-07-29/30):
#
#   * RUNAWAY IS REAL: the dense tables (37 and 41 rows) do not converge. Locally they blew
#     past 6000 tokens still generating; the WORK vLLM log shows ~6.5 MINUTES of continuous
#     output on one crop (~16,000+ tokens) at `Running: 1 reqs, Waiting: 0` — so it is the
#     decode, not queueing.
#   * THE BUDGET IS SMALL: work generates at ~46 tok/s (observed, single-stream 31B), and
#     LiteLLM cuts the client off at 60s. That is a ceiling of ~2,700 tokens — far less than
#     the "H200 is fast so tokens are cheap" intuition suggests.
#
# So the bound must satisfy: (prefill + max_tokens/throughput) < the infra timeout. At
# 46 tok/s with a 60s ceiling and a few seconds of prefill, 2048 lands near ~45s and
# COMPLETES; 4096 would need ~89s and would still be killed — a cap that never fires is
# not a cap. Tune VISION_MAX_TOKENS per deployment: it is a function of that deployment's
# throughput and timeout, not a universal constant.
#
# NB a legitimately huge table can exceed this (Diodes p3 is THREE (EOL, Replacement)
# column-pairs per row => ~111 parts => ~3,900 tokens, which simply does not fit in a 60s
# 46 tok/s budget). That is correct behaviour here: it truncates, is DETECTED, and the
# reviewer is told parts may be missing — instead of 3x60s of retries and an opaque
# timeout. Actually EXTRACTING those parts wants the text-layer path (these notices are
# born-digital; pdfplumber reads the same tables exactly, in under a second), not a
# bigger token budget.
#
# MEASURED ELSEWHERE, 2026-09-22 — the "per deployment" caveat above is not
# hypothetical, and the sandbox is the worked example. Against Ollama on a
# discrete Radeon (no LiteLLM, 600s client timeout, 17-21 tok/s measured over 8
# crops) the binding constraint is ~12,000 tokens, not ~2,700, and the two
# densest crops in the corpus emit 2,840 and 3,472 tokens. There 2048 truncated
# both: PCN23-002 returned 0 of 18 parts and onsemi_Generic_IPCN25300X 2 of 19.
# values-sandbox.yaml therefore sets 8192. This default is deliberately NOT
# changed — it is right for the 46 tok/s + 60s deployment described above, and
# the two deployments disagree by 4x on throughput and 10x on timeout.
VISION_MAX_TOKENS = int(os.getenv("VISION_MAX_TOKENS", "2048"))

# Greedy decoding for the HEADER pass. NOT a tuning knob -- an identity requirement.
#
# `ExtractHeader` (client `LLM`, gpt-oss) reads the SAME 1713 input tokens every fire and
# answers differently. On `EOL-36_BYV34-400,-BYV34-500` it produced `mfr` = "TT Electronics"
# against a SEMELAB document -- a value that is not in the PDF at all -- and flipped
# `doc_type` PCN/PDN/PCN across repeated fires on identical input. The client set no
# temperature, so the server default applied and the call SAMPLED; a sampled header means
# doc_id, mfr and doc_type -- all identity/routing fields -- can come back different on a
# re-run of the same document.
#
# Deliberately NOT env-overridable, same reasoning as `VISION_TEMPERATURE` would be: an env
# knob is a way for the pin to be quietly undone in the one environment where it matters.
HEADER_TEMPERATURE = 0

# Greedy decoding for the parts pass. NOT a tuning knob -- an identity requirement.
#
# Measured 2026-09-27 on pin sha256:0136991e: `ADI_PDN_23_0120` emitted 'AD7873ACPZ' in
# one corpus run and '7873ACPZ' in two others from BYTE-IDENTICAL input -- same prompt,
# 1299 in-tokens in all three, and that notice has no tier-1 activity at all, so no code
# path differed between the runs. The client set no temperature, so the server default
# applied and the call SAMPLED.
#
# That makes a corpus score a draw rather than a measurement: 898/898 can pass or fail on
# unchanged code, and a gate that happens to land heads is worse than no gate, because it
# certifies whatever was sampled. Every "898/898" recorded before this date is one sample,
# not a property of the extractor.
#
# Why this notice is sampling-sensitive at all: its stored table cell is CLIPPED on the
# left edge -- the header reads 'del' for 'Model', the cell reads '7873ACPZ' for
# 'AD7873ACPZ' -- so the model must RECOVER two missing characters from context. Greedy
# decoding makes that recovery repeatable; it does not make it correct. The clipping is
# the real defect and is fixed separately.
#
# Deliberately NOT env-overridable, unlike the cap above: an env knob is a way for the
# gate to be quietly unpinned in the one environment where it matters.
#
# The closing note here used to read that the text client (`client<llm> LLM` in
# baml_src/main.baml) "still samples ... named in the PR rather than changed here". It is
# now pinned too -- see HEADER_TEMPERATURE above -- because leaving it sampling produced a
# fabricated manufacturer. Neither client is pinned in main.baml: both are built at runtime
# through `baml_py.ClientRegistry`, so no other domain sharing `LLM` is affected.
VISION_TEMPERATURE = 0

# Early warning for the bound above. Truncation is only detectable AT the cap, by
# which point rows are already lost; a crop that emits close to the cap is the last
# observable state before that happens, and the ratio is the ONLY signal available
# ahead of the loss. A denser table than any yet seen would cross the cap silently
# otherwise — it fails open, so nothing would be raised. 0.85 comes from the
# measured corpus: the densest crop emits 3,472 tokens, which is 85% of 4096 and
# 42% of the 8192 the sandbox now sets, so a crop at or above this ratio is outside
# everything that has been observed and is worth a human look.
VISION_NEAR_CAP_RATIO = float(os.getenv("VISION_NEAR_CAP_RATIO", "0.85"))

# The row-short cross-check's baseline floor. A DECLINED grid is, by definition, one
# whose columns could not be decided — `n_rows` is a lower bound salvaged from an
# otherwise-discarded table, not a confident count. Below this many rows that count is
# not strong enough evidence to accuse the vision pass of dropping something: measured
# 2026-09-23, three findings on onsemi_Generic_IPCN25300X (tier1 1 vs vision 0, tier1 4
# vs vision 0 x2) were all noise from thin declines (n_rows 1 and 4) on pages vision read
# correctly. This is a DELIBERATE threshold that trades detecting small shortfalls for
# not manufacturing false ones — a real 2-or-3-row loss below the floor goes unflagged.
MIN_ROW_SHORT_BASELINE = 5


# THE PCN24-029 ROUTER GAP. That notice prints a single MPN, `TC4-1TX+`, under the label
# "MODELS AFFECTED" with no table at all — not a borderless table unstructured missed, an
# honest absence of one. `provenance.table_elements` therefore returns zero Table
# elements, the router's `elif not tables:` branch takes the header-only path, and vision
# is never invoked. The document's only part number is silently lost with nothing to flag
# it: no crop failed, because no crop was ever attempted.
#
# Vocabulary, not a regex on the MPN alone, because an MPN-shaped token appears in plenty
# of table-less prose that carries no affected part (a revision string, a date code, a
# document number) — see AFFECTED_HEADERS in table_text_layer.py for the same design
# choice applied to column headers. A label is what turns "this text contains an
# alphanumeric token" into "this document is ADVERTISING an affected part".
_AFFECTED_LABELS = ("models affected", "affected models", "affected parts",
                    "parts affected", "affected part numbers", "affected devices",
                    "affected model", "model affected")


def _has_part_shaped_text(full_text: str) -> bool:
    """True only when full_text BOTH names an affected-parts section AND carries at
    least one MPN-shaped token — the gate that routes a table-less document like
    PCN24-029 to vision instead of silently taking the header-only path.

    BOTH conditions are required, and this gate is deliberately TIGHT rather than loose:
    every table-less document that passes it costs a FULL vision call (~100s measured on
    the deployed endpoint — see VISION_MAX_TOKENS above), so a loose gate turns every
    ordinary header-only notice — the common case, a process-change notification with no
    parts list at all — into a slow one for nothing. The label is what distinguishes "this
    document advertises affected parts" from "this document merely contains alphanumeric
    tokens": a document number, a revision code or a footer date-stamp all look exactly
    like an MPN to a plausibility floor that only checks shape.
    """
    text = full_text or ""
    lowered = text.lower()
    if not any(label in lowered for label in _AFFECTED_LABELS):
        return False
    for token in re.split(r"[\s,]+", text):
        token = token.strip()
        # A LETTER **and** a digit, not `looks_like_mpn` alone. That helper's floor is
        # "contains a digit", which is the right floor for a cell already known to sit in
        # a parts column but far too low here, where the candidate is any whitespace-
        # delimited token in the whole document: `2026` clears it, and so does every page
        # number, revision count and date fragment on the page. Requiring both classes of
        # character is what actually implements the tightness this gate is FOR — `TC4-1TX+`
        # passes, a bare year does not.
        if (len(token) >= 4 and text_layer.looks_like_mpn(token)
                and any(ch.isalpha() for ch in token)):
            return True
    return False


def _vision_call_opts():
    """(baml_options, collector) for the VISION pass: an output bound + truncation detection.

    Returns a collector because BAML **FAILS OPEN** on a truncated response — verified
    against the live model: a response cut at the cap raised NOTHING and returned a
    short/empty list. So a bound WITHOUT a truncation check would silently hand back
    "25 of 41 parts" as though it were the whole table — fabricated completeness, the
    exact laundering the review chain exists to prevent. The caller MUST treat a
    truncated call as a FAILED crop (see _extract_parts).

    `finish_reason` is not exposed by the collector for this provider, so truncation is
    detected as `usage.output_tokens >= VISION_MAX_TOKENS` — provider-independent and
    using what IS observable.

    The bound is applied via ClientRegistry rather than in `main.baml` DELIBERATELY: it
    keeps ONE source of truth (this constant) for both the cap and the check, and avoids
    the BAML deploy seam where an edited .baml is not live until `baml-cli generate` runs.
    """
    from baml_py import AbortController, ClientRegistry, Collector
    ms = int(os.getenv("LLM_REQUEST_TIMEOUT_MS", "600000"))
    cr = ClientRegistry()
    cr.add_llm_client("VisionBounded", "openai-generic", {
        "base_url": os.environ.get("VISION_LLM_BASE_URL", ""),
        "api_key": os.environ.get("VISION_LLM_API_KEY", "") or "any",
        "model": os.environ.get("VISION_LLM_MODEL", ""),
        "max_tokens": VISION_MAX_TOKENS,
        "temperature": VISION_TEMPERATURE,
    })
    cr.set_primary("VisionBounded")
    collector = Collector(name="vision")
    return ({"abort_controller": AbortController(timeout_ms=ms),
             "client_registry": cr, "collector": collector}, collector)


def _vision_output_tokens(collector) -> Optional[int]:
    """Output tokens of the collector's last call, or None if unavailable (never raises —
    a missing usage figure must not itself break an extraction)."""
    try:
        return collector.last.usage.output_tokens
    except Exception:  # noqa: BLE001
        return None


def _baml_call_opts() -> dict:
    """Fresh BAML call options with a generous request timeout.

    Dense-table vision extraction on a 31B model is slow and was 408-timing-out
    on multi-row crops under the default request ceiling. AbortController is
    single-use ('once aborted, forever aborted'), so build a fresh one per call.
    Tunable via LLM_REQUEST_TIMEOUT_MS (default 600000 = 10 min).
    """
    from baml_py import AbortController
    ms = int(os.getenv("LLM_REQUEST_TIMEOUT_MS", "600000"))
    return {"abort_controller": AbortController(timeout_ms=ms)}


def _header_call_opts() -> dict:
    """BAML call options for the HEADER pass: greedy decoding via ClientRegistry.

    Fixes two observed defects, both from the SAME root cause (an un-pinned temperature
    on identical 1713-token input): a fabricated `mfr` ("TT Electronics" against a
    SEMELAB document — not present anywhere in the PDF), and `doc_type` flipping
    PCN/PDN/PCN across repeated fires with nothing about the document changed.

    The bound is applied via ClientRegistry rather than in `main.baml`, for the SAME
    reason as `_vision_call_opts`: it keeps the pin live on pod restart, with no
    `baml-cli generate` deploy seam between an edited `.baml` file and the running
    pod. `main.baml`'s declared `client<llm> LLM` block is mirrored here field-for-field
    (including the Ollama-only `num_ctx` passthrough) so registering this client does
    not silently drop config the declared one carries.

    No Collector: unlike the vision pass, there is no truncation check on this pass.
    """
    from baml_py import AbortController, ClientRegistry
    ms = int(os.getenv("LLM_REQUEST_TIMEOUT_MS", "600000"))
    cr = ClientRegistry()
    options = {
        "base_url": os.environ.get("LLM_BASE_URL", ""),
        "api_key": os.environ.get("LLM_API_KEY", "") or "any",
        "model": os.environ.get("LLM_MODEL", ""),
        "temperature": HEADER_TEMPERATURE,
    }
    num_ctx = os.environ.get("LLM_NUM_CTX")
    if num_ctx:
        try:
            options["options"] = {"num_ctx": int(num_ctx)}
        except ValueError:
            pass
    cr.add_llm_client("HeaderBounded", "openai-generic", options)
    cr.set_primary("HeaderBounded")
    return {"abort_controller": AbortController(timeout_ms=ms), "client_registry": cr}


def _grid_to_text(grid: List[List[Any]]) -> str:
    """A tab-separated rendering of a declined grid in which every index the model is asked
    to return is PRINTED IN THE TEXT rather than counted.

    Data columns are headed `c0 c1 c2 …`, and each row is labelled `[row N]`. Both halves
    are load-bearing:

    - The row label MUST NOT read as a data column. The first version of this function put
      a bare `str(i)` in the leading tab-separated field, which shows the model a table
      whose first column is the row number — an open invitation to answer `1` for the FIRST
      data column. That off-by-one would silently hand back the replacement column as
      `affected_col`, mispairing every row, and NO test can catch it: the label call is
      stubbed in tests, so the defect lives only in the wording the model actually sees.
    - A printed `cN` heading means `affected_col` is READ OFF the grid instead of inferred
      by counting, which is the difference between a model that miscounts and a model that
      copies.

    `n_cols`, `_valid_grid_roles` and the emission loop in `_extract_parts` are all
    DATA-relative (`row[affected_col]`), so this rendering is the single place the two
    conventions could drift apart. `tests/test_grid_forwarding_seal.py` pins the contract.
    """
    n_cols = max((len(r) for r in grid), default=0)
    lines = ["[row]\t" + "\t".join(f"c{j}" for j in range(n_cols))]
    for i, row in enumerate(grid):
        cells = [(c or "").strip() for c in row] + [""] * (n_cols - len(row))
        lines.append(f"[row {i}]\t" + "\t".join(cells))
    return "\n".join(lines)


def _valid_grid_roles(roles: Any, n_cols: int) -> bool:
    """True when every column index `LabelGridColumns` returned is IN RANGE of the grid it
    was given. A model can name a column that does not exist (miscounting, or echoing a
    stale n_cols); trusting that would either read garbage out of the wrong column or raise
    a plain IndexError deep in the row-emission loop. Checked up front and treated as a
    label failure (falls back to the pixel path) rather than either of those.

    `header_rows` is deliberately NOT validated here — per the spec, an out-of-range header
    row index is silently ignored at emission time rather than failing the whole label.

    A NULL `affected_col` is NOT an invalid label and is not rejected here: it is the
    model declining the table, handled separately by the caller. See
    `_GRID_NO_PARTS_COL_NOTE`.
    """
    if roles.affected_col is None:
        return True
    if not (0 <= roles.affected_col < n_cols):
        return False
    for col in (roles.replacement_col, roles.ltb_date_col):
        if col is not None and not (0 <= col < n_cols):
            return False
    return True


# Why `affected_col` is allowed to come back NULL.
#
# Measured on the 9-notice corpus at pin sha256:0136991e (507013f), which scored
# 897/898 where the previous pin scored 898/898. The single regression:
# onsemi_Generic_IPCN25300X emitted `'20kAlSiCu, 40kAlSi'` — a wire-bond material — as
# an affected MPN. The label call's own `reason` explained exactly why: "'Before Change
# Description' in c3 (affected state) and 'After Change Description' in c4". That table
# is a CHANGE-DESCRIPTION table. It has no parts column at all.
#
# The model was not wrong; it was not ALLOWED to be right. `affected_col` was a required
# int and the prompt said "Always pick your best candidate, even if you are not fully
# certain", so a declined non-parts table could only ever produce a guess, and the grid
# then faithfully emitted whatever sat in the guessed column. That is the SAME defect
# this whole feature was built to fix, one tier along: tier 1 could not say "declined"
# and returned [], so tier 2 could not say "no parts here" and returned a row.
#
# `looks_like_mpn` is not the fix. It let this string through (it has one space and 18
# characters, under `_is_prose_cell`'s 3-space/30-char thresholds), and tightening a
# predicate that tier 1 uses everywhere to catch one wire-bond alloy trades a precision
# bug for a recall risk across all 898 parts.
#
# So: null `affected_col` means "this table has no affected-part column". The page then
# DEGRADES TO THE PIXEL PATH rather than emitting nothing, which is deliberate and
# recall-safe — the pixel path is what ran before grid forwarding existed and what
# scored 898/898, and on this very table it correctly returned []. A model wrongly
# declining a real parts table therefore costs a vision call, never a row.
_GRID_NO_PARTS_COL_NOTE = __doc__


# --------------------------------------------------------------------------- #
# Plugin
# --------------------------------------------------------------------------- #
class SustainmentPlugin(AugmentationPlugin):
    """PCN/PDN two-pass extraction with a router, merge, validation + review lane."""

    # The prompt files this plugin's extraction actually uses. Declared here so
    # AugmentationPlugin._ensure_prompts_available (called once, at the top of
    # process_fulltext below) can validate BOTH exist up front and name every
    # missing one at once, rather than discovering a missing prompt lazily, deep
    # inside a per-document extraction call that a broad handler is waiting to
    # degrade instead of raise.
    REQUIRED_PROMPT_FILES = [
        "prompts/sustainment_header_instructions.md",
        "prompts/sustainment_parts_instructions.md",
        "prompts/sustainment_grid_columns_instructions.md",
        "prompts/sustainment_transcribe_page.md",
    ]

    @traced(name="extract header (gpt-oss)")
    def _extract_header(self, full_text: str):
        from doc_tools.baml_client.sync_client import b
        prompt = self._get_dynamic_prompt(
            prompt_name="sustainment_header_instructions",
            fallback_file="prompts/sustainment_header_instructions.md",
        )
        prompt += render_candidate_block(ltb_candidates(full_text))
        return b.ExtractHeader(doc=full_text, system_instructions=prompt,
                               baml_options=_header_call_opts())

    def _extract_parts_text_layer(self, manifest: Optional[dict], s3_client,
                                  bucket: Optional[str]) -> Tuple[List[dict], dict]:
        """TIER 1: read the parts tables from the PDF's own TEXT LAYER (deterministic).

        These notices are born-digital — their tables are not pictures of tables. Measured
        on Diodes PCN 2683: the vision pass produced ZERO parts at work (runaway decode
        killed at 60s) while the text layer yielded 402 parts with exact per-cell bboxes
        in under a second. So vision is the FALLBACK for scans, not the default for text.

        Returns ([], stats) when the tier does not apply — no source PDF, no text layer,
        or no recognizable parts table — and the caller falls through to vision. Never
        raises: a tier-1 miss must degrade to tier 2, not fail the document.
        """
        stats = {"text_layer_pages": 0, "text_layer_parts": 0, "text_layer_used": False}
        key = (manifest or {}).get("source_key")
        if not key or s3_client is None or not bucket:
            return [], stats
        try:
            import pdfplumber  # noqa: PLC0415 — heavy import, only on the text-layer path
        except Exception as e:  # noqa: BLE001
            # LOUD, not silent. A missing tier-1 dependency means EVERY born-digital
            # document silently falls through to the vision path — which on dense tables
            # fabricates (measured: 84 invented MPNs, 100 of 111 real ones missed). A
            # quiet degrade here would hide a deployment error behind plausible garbage.
            print(f"[SustainmentPlugin] TEXT-LAYER TIER UNAVAILABLE — pdfplumber not importable "
                  f"({e}). Every born-digital notice will fall back to the vision pass, which is "
                  f"slower AND less accurate on dense tables. Install pdfplumber.")
            stats["text_layer_unavailable"] = True
            return [], stats
        try:
            body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
            parts: List[dict] = []
            declines: List[dict] = []
            with pdfplumber.open(io.BytesIO(body)) as pdf:
                def _born_digital_pages():
                    """(page_number, page) for the pages tier 1 can actually read."""
                    for pno, page in enumerate(pdf.pages, start=1):
                        if not text_layer.page_has_text_layer(page):
                            continue
                        stats["text_layer_pages"] += 1
                        yield pno, page
                # parts_and_declines_from_pages OWNS the page loop because a parts table
                # spanning pages prints its header only once: page 2 onwards is an
                # anonymous grid, and read per-page every column of an `EOL | Replacement`
                # continuation was emitted as a discontinued part (measured: 34% of one
                # notice's 402). It ALSO carries forward every table whose columns could
                # not be decided — that decline's row count is the router's only
                # independent check on the vision pass, so it must survive even when this
                # tier ends up producing zero parts (see the stats.update below).
                parts, declines = text_layer.parts_and_declines_from_pages(_born_digital_pages())
        except Exception as e:  # noqa: BLE001 — degrade to vision, never fail the doc
            print(f"[SustainmentPlugin] text-layer pass unavailable ({e}); falling back to vision")
            return [], stats
        # LOAD-BEARING ORDER: this is set BEFORE the `if not parts` early return below,
        # because a decline IS the case where `parts` is empty — pdfplumber read a table
        # and could not decide its columns, so it produced zero rows. Setting this after
        # that return would mean the one case this detector exists for never reaches it.
        stats["text_layer_declines"] = declines
        if not parts:
            return [], stats
        stats["text_layer_parts"] = len(parts)
        stats["text_layer_used"] = True
        # Shape to the same per-part dict the vision pass produces. The bbox/page ride
        # along as PROVENANCE — strictly better than string-matching an MPN against a
        # positioned OCR index, and tight to the CELL rather than the whole table.
        out = [{
            "affected_mpn": p["affected_mpn"],
            "affected_mpn_source": p["affected_mpn"],   # verbatim: the cell IS the source
            "replacement_mpn": p.get("replacement_mpn"),
            "replacement_mpn_source": p.get("replacement_mpn"),
            "ltb_date": None,          # per-row dates are not a column in this shape;
            "ltb_date_source": None,   # the header pass supplies the doc-level date
            "text_layer_bbox": p.get("bbox"),
            "text_layer_replacement_bbox": p.get("replacement_bbox"),
            "text_layer_page": p.get("page_number"),
            "text_layer_page_dims": p.get("page_dims"),
        } for p in parts]
        return out, stats

    @traced(name="extract parts vision (gemma)")
    def _extract_parts(self, tables: List[dict], manifest: Optional[dict],
                       s3_client, full_text: str,
                       tl_declines: Optional[List[dict]] = None) -> Tuple[List[dict], dict]:
        from doc_tools.baml_client.sync_client import b
        from baml_py import Image
        prompt = self._get_dynamic_prompt(
            prompt_name="sustainment_parts_instructions",
            fallback_file="prompts/sustainment_parts_instructions.md",
        )
        grid_prompt = self._get_dynamic_prompt(
            prompt_name="sustainment_grid_columns_instructions",
            fallback_file="prompts/sustainment_grid_columns_instructions.md",
        )
        embedded = (manifest or {}).get("embedded_images", {}) or {}
        all_parts: List[dict] = []
        n_crops, missing, failed, truncated, near_cap = 0, 0, 0, 0, 0
        grid_forwarded, grid_label_failed, grid_rows_emitted = 0, 0, 0
        grid_no_parts_col = 0
        tl_repairs: List[dict] = []
        # The row-short cross-check needs, PER PAGE, how many rows vision actually
        # returned and whether that page's crop is already known-bad (failed/truncated).
        # Keyed on the crop's page_number (from unstructured metadata) rather than on the
        # crop itself, because tier 1's declines are also page-scoped — a table can span
        # one crop and one pdfplumber grid on the same page, and that page number is the
        # only key both sides share.
        rows_by_page: Dict[Any, int] = {}
        failed_pages: set = set()

        # ONE map, built ONCE: page_number -> this page's declined grids (tier 1 saw the
        # table, exact cell text and all, but could not decide what the columns MEANT).
        # The row-short cross-check further below used to rebuild an equivalent map from
        # `tl_declines` AFTER this loop finished; it now reuses THIS one instead of
        # rebuilding it, so the two paths cannot drift apart on what "this page's declines"
        # means.
        declines_by_page: Dict[Any, List[dict]] = {}
        for d in (tl_declines or []):
            declines_by_page.setdefault(d.get("page_number"), []).append(d)

        # GRID FORWARDING. A page carrying >=1 declined grid gets its columns LABELED by
        # vision instead of having its parts RE-READ from a fresh crop — the whole point of
        # this branch (see table_text_layer.GridDecline / is_part_row docstrings): a
        # clipped or re-cut crop can cost a column label, but it can no longer cost a row,
        # because every part string below comes verbatim out of `grid`, never out of
        # LabelGridColumns' response. Runs BEFORE the ordinary per-crop loop so that loop
        # can skip every element on a page this succeeded for (`grid_handled_pages`) —
        # ExtractParts must not also run for a page tier 2 already handled by labeling.
        elements_by_page: Dict[Any, List[dict]] = {}
        for el in tables:
            elements_by_page.setdefault((el.get("metadata") or {}).get("page_number"), []).append(el)

        grid_handled_pages: set = set()
        for page_no, page_declines in declines_by_page.items():
            page_images = []
            for el in elements_by_page.get(page_no, []):
                url = provenance.resolve_element_image(el, embedded)
                if url:
                    media, b64 = _fetch_image_b64(s3_client, url)
                    if b64:
                        page_images.append(Image.from_base64(media, b64))
            # `page_images` may end up EMPTY (no crop was ever made, or its fetch failed) —
            # that is fine and expected: the prompt tells the model to label from the grid
            # text alone when the image is unusable, and the grid text is what carries the
            # real evidence anyway.
            page_ok = True
            page_emitted = 0
            for d in page_declines:
                grid = d.get("grid") or []
                if not grid:
                    continue
                n_cols = max((len(r) for r in grid), default=0)
                if n_cols == 0:
                    continue
                try:
                    opts, collector = _vision_call_opts()
                    roles = b.LabelGridColumns(
                        grid_text=_grid_to_text(grid), n_cols=n_cols,
                        table_images=page_images, system_instructions=grid_prompt,
                        baml_options=opts,
                    )
                    used = _vision_output_tokens(collector)
                    if used is not None and used >= VISION_MAX_TOKENS:
                        print(f"[SustainmentPlugin] LabelGridColumns TRUNCATED on page "
                              f"{page_no} — degrading this page to the pixel path")
                        page_ok = False
                        continue
                    if not _valid_grid_roles(roles, n_cols):
                        print(f"[SustainmentPlugin] LabelGridColumns returned an "
                              f"out-of-range column index on page {page_no} "
                              f"(affected_col={roles.affected_col!r}, "
                              f"replacement_col={roles.replacement_col!r}, "
                              f"ltb_date_col={roles.ltb_date_col!r}, n_cols={n_cols}) — "
                              f"degrading this page to the pixel path")
                        page_ok = False
                        continue
                except Exception as e:  # noqa: BLE001 — degrade, never fail the document
                    print(f"[SustainmentPlugin] LabelGridColumns failed on page "
                          f"{page_no}: {e} — degrading this page to the pixel path")
                    page_ok = False
                    continue
                if roles.affected_col is None:
                    # The model declined the table: no affected-part column exists (a
                    # change-description table, a spec table, a revision-history table).
                    # Counted apart from grid_label_failed because it is not a failure —
                    # it is the answer, and the one the old required-int schema could not
                    # express. See _GRID_NO_PARTS_COL_NOTE.
                    print(f"[SustainmentPlugin] LabelGridColumns reports NO affected-part "
                          f"column on page {page_no} ({roles.reason!r}) — degrading this "
                          f"page to the pixel path")
                    grid_no_parts_col += 1
                    page_ok = False
                    continue
                # header_rows entries out of range are IGNORED, not a validation failure —
                # the model naming a header row that does not exist costs nothing, unlike
                # an out-of-range affected_col/replacement_col/ltb_date_col above.
                header_rows = {i for i in (roles.header_rows or []) if 0 <= i < len(grid)}
                for i, row in enumerate(grid):
                    if i in header_rows or not text_layer.is_part_row(row):
                        continue
                    a_col = roles.affected_col
                    affected = (row[a_col] or "").strip() if a_col < len(row) else ""
                    if not affected or not text_layer.looks_like_mpn(affected):
                        continue
                    rep = None
                    r_col = roles.replacement_col
                    if r_col is not None and r_col < len(row):
                        rep = (row[r_col] or "").strip() or None
                    ltb = None
                    l_col = roles.ltb_date_col
                    if l_col is not None and l_col < len(row):
                        ltb = (row[l_col] or "").strip() or None
                    # VERBATIM, both value and "source" — the grid cell IS the source, and
                    # NEVER pixels. Stripped of surrounding whitespace only: no
                    # normalization, no case change, no hyphen fixing (see the GridDecline
                    # / GridColumnRoles docstrings for why this is the entire point).
                    all_parts.append({
                        "affected_mpn": affected, "affected_mpn_source": affected,
                        "replacement_mpn": rep, "replacement_mpn_source": rep,
                        "ltb_date": ltb, "ltb_date_source": ltb,
                    })
                    page_emitted += 1
            if page_ok and page_emitted > 0:
                grid_forwarded += 1
                grid_rows_emitted += page_emitted
                rows_by_page[page_no] = rows_by_page.get(page_no, 0) + page_emitted
                grid_handled_pages.add(page_no)
            else:
                # DEGRADE, NEVER FAIL: a label failure, a truncation, a bad validation, or
                # simply zero rows emitted all fall through to the EXISTING pixel path for
                # every element on this page — this page's grid attempt (if any rows WERE
                # emitted before a later decline on the same page failed) must not survive
                # as a partial result sitting alongside a full pixel-path re-read of the
                # same page.
                grid_label_failed += 1
                if page_emitted:
                    del all_parts[-page_emitted:]

        # The page TEXT LAYER, tokenized once for the clipped-crop repair below. Built
        # from `full_text` and NOT from any `text_as_html`: on a cut crop the HTML carries
        # the SAME cut, so checking a clipped string against it would confirm the cut
        # rather than catch it (measured on ADI_PDN_23_0120 -- see prefer_text_layer_mpn).
        doc_tokens = text_layer.doc_text_tokens(full_text)
        for el in tables:
            meta = el.get("metadata") or {}
            page_no = meta.get("page_number")
            if page_no in grid_handled_pages:
                # Already extracted, verbatim, from the grid above — ExtractParts (the
                # pixel path) must NOT also run for this page, or its re-read from pixels
                # could reintroduce exactly the misread this whole change exists to stop.
                continue
            html = meta.get("text_as_html", "") or ""
            ocr = el.get("text", "") or full_text
            images = []
            url = provenance.resolve_element_image(el, embedded)
            if url:
                media, b64 = _fetch_image_b64(s3_client, url)
                if b64:
                    images.append(Image.from_base64(media, b64))
                    n_crops += 1
                else:
                    missing += 1
            else:
                missing += 1  # borderless / undetected-crop table -> OCR+HTML only
            try:
                opts, collector = _vision_call_opts()
                res = b.ExtractParts(ocr_text=ocr, html_table=html,
                                     table_images=images, system_instructions=prompt,
                                     baml_options=opts)
                # TRUNCATION IS A FAILURE, NOT A PARTIAL SUCCESS. BAML fails OPEN here:
                # a response cut at the cap parses to whatever complete objects it can
                # and raises nothing, so accepting it would report "25 of 41 parts" as
                # the whole table — a silent partial that looks clean, which is the one
                # thing this pipeline must never produce. Drop the rows and count the
                # crop failed; that flags the doc and the reviewer is TOLD parts may be
                # missing (doc_flags -> the review card's warning banner).
                used = _vision_output_tokens(collector)
                if used is not None and used >= VISION_MAX_TOKENS:
                    failed += 1
                    truncated += 1
                    failed_pages.add(page_no)
                    print(f"[SustainmentPlugin] ExtractParts TRUNCATED at the {VISION_MAX_TOKENS}-token "
                          f"bound (runaway decode on a dense table) — discarding this crop's "
                          f"{len(res or [])} partial row(s) rather than reporting them as complete")
                    continue
                # Not truncated, but close enough that the next document of this
                # shape may not be. Recorded per crop so the ratio is visible in
                # logs before it ever becomes a loss.
                if used is not None:
                    ratio = used / VISION_MAX_TOKENS
                    if ratio >= VISION_NEAR_CAP_RATIO:
                        near_cap += 1
                        print(f"[SustainmentPlugin] ExtractParts NEAR CAP: {used}/"
                              f"{VISION_MAX_TOKENS} output tokens ({ratio:.0%}) — this crop "
                              f"completed, but a denser table would truncate and lose rows")
                # SUCCESS PATH ONLY — a page that reaches here neither truncated nor
                # raised, so its row count is a fair thing to compare against tier 1's.
                # Accumulated rather than assigned: a table that spans multiple crops on
                # the SAME page (a dense table banded into pieces) must not have its
                # later crops overwrite the count from its earlier ones.
                rows_by_page[page_no] = rows_by_page.get(page_no, 0) + len(res or [])
                for p in (res or []):
                    d = part_to_dict(p)
                    # PIXEL PATH ONLY. The grid path above reads its strings from
                    # pdfplumber cells, which are never clipped, so it needs no repair;
                    # these rows came from an IMAGE that may have been cut through the
                    # glyphs on any edge.
                    # The `_source` companions are repaired by the SAME rule, not copied
                    # from the repaired value. They are the provenance JOIN KEY (see the
                    # @description in sustainment.baml): build_review_items feeds them to
                    # resolve_value, which string-matches them against the positioned OCR
                    # index to place the reviewer's highlight box. A clipped fragment left
                    # there resolves to the wrong span or to nothing at all, so the fix
                    # would be invisible on the review card even though the MPN was right.
                    # Repairing them independently rather than assigning the new value
                    # keeps every field held to the same evidence, with no special case.
                    # The audit trail of what the model actually returned is in
                    # `text_layer_repair_detail`, which records every field it changed.
                    for key in ("affected_mpn", "affected_mpn_source",
                                "replacement_mpn", "replacement_mpn_source"):
                        was = d.get(key)
                        now = text_layer.prefer_text_layer_mpn(was, doc_tokens)
                        if now != was:
                            d[key] = now
                            tl_repairs.append({"page_number": page_no, "field": key,
                                               "from": was, "to": now})
                            print(f"[SustainmentPlugin] clipped-crop repair on page "
                                  f"{page_no}: {key} {was!r} -> {now!r} (absent verbatim "
                                  f"from the text layer; unique longer MPN there)")
                    all_parts.append(d)
            except Exception as e:  # noqa: BLE001
                # A per-crop failure (commonly a vision timeout on a dense table)
                # loses that crop's rows. Count it so process_fulltext can flag
                # the doc needs_review — a silent partial must never look clean.
                failed += 1
                failed_pages.add(page_no)
                print(f"[SustainmentPlugin] ExtractParts failed on a table crop: {e}")
        # crops_truncated is a SUBSET of crops_failed, surfaced separately because it names a
        # DIFFERENT cause with a different fix: not "the model was slow / errored" but "the
        # decode did not converge on this table". Distinguishing them is how we'll know whether
        # banding (or a text-layer path) actually helps, instead of inferring it.
        #
        # ROW-COUNT CROSS-CHECK — the silent class this pipeline previously had no way to
        # see. Every failure path above (truncated, missing image, an outright exception)
        # already produces a signal; this one does not. A crop can complete, raise
        # nothing, and STILL come back with fewer rows than pdfplumber counted on the
        # SAME page — the `SYTX9-122HP-1+` shape on PCN23-002: the last row of the table,
        # sitting immediately above the page footer, dropped with needs_review=False and
        # nothing in crops_failed or crops_truncated to say so. Tier 1's decline record
        # (a table it saw but declined to parse — NOT an empty table) carries exactly the
        # row count needed to catch this, so it is compared here.
        #
        # AGGREGATED PER PAGE, not per decline: `tl_declines` has one entry per declined
        # TABLE, but `rows_by_page` is a PAGE total — a page with 3 declined tables was
        # producing up to 3 findings against the same one page total (measured: 2 of
        # onsemi_Generic_IPCN25300X's 3 false positives on 2026-09-23 were exactly this,
        # both declines on its page 2 compared separately against the same page-2 vision
        # count). Grouping by page and taking MAX (not sum) across that page's declines
        # is the fix — the page total covers at least the largest table on it; summing
        # would false-positive whenever one page holds several declined tables.
        # Reuses the SAME declines_by_page map built above (before the grid-forwarding
        # loop) rather than rebuilding it — one map, filtered per-purpose here, so the
        # grid-forwarding path and this cross-check can never disagree about what tier 1
        # declined on a given page.
        row_short: List[Dict[str, Any]] = []
        for page, all_ds in declines_by_page.items():
            ds = [d for d in all_ds if (d.get("n_rows") or 0) >= MIN_ROW_SHORT_BASELINE]
            # Baseline floor: a DECLINED grid is one whose columns could not be
            # decided, so its row count is not confident enough evidence to accuse
            # the vision pass below this many rows — see MIN_ROW_SHORT_BASELINE.
            if not ds:
                continue
            if page not in rows_by_page:
                continue  # vision never produced a successful crop for this page at all
            if page in failed_pages:
                # A crop that failed or truncated on this page is ALREADY covered by
                # PARTS MAY BE MISSING above; double-flagging it here would blur what
                # THIS signal means. row_short exists to name the OTHER class — a crop
                # that completed, reported no error, and still came back short — so a
                # page already known bad for a different, louder reason is skipped.
                continue
            best = max(ds, key=lambda d: d["n_rows"])
            if rows_by_page[page] < best["n_rows"]:
                row_short.append({"page_number": page, "tier1_rows": best["n_rows"],
                                  "vision_rows": rows_by_page[page], "n_declines": len(ds)})
        return all_parts, {"n_crops_used": n_crops, "crops_missing": missing,
                           "crops_failed": failed, "crops_truncated": truncated,
                           "crops_near_cap": near_cap, "crops_row_short": len(row_short),
                           "row_short_detail": row_short,
                           "grid_forwarded": grid_forwarded, "grid_label_failed": grid_label_failed,
                           "grid_rows_emitted": grid_rows_emitted,
                           "grid_no_parts_col": grid_no_parts_col,
                           "text_layer_repairs": len(tl_repairs),
                           "text_layer_repair_detail": tl_repairs}

    def _transcribe_pages_witness(self, manifest: Optional[dict], s3_client) -> List[dict]:
        """THE SECOND WITNESS: one positioned-index record per page, read from the page's
        own PIXELS via TranscribePage, for `sustainment_header_trust.refuse_unsourced_header_values`
        to consult when the text layer fails to corroborate a header value (see
        `doc_tools.utils.text_layer_health` and that module's docstring).

        Built ONLY on demand by the caller — this method does no gating of its own beyond
        the cheap short-circuits below (no manifest, no page renders, no vision endpoint).
        The document-level "is this worth paying for" decision (is the text layer actually
        degraded) lives in `_extract_fulltext`, once, not here: this method has no opinion
        on when it should run, only on how to run it.

        Never raises. Each page is fetched and transcribed independently and wrapped in its
        own try/except, so one bad page (a failed fetch, a vision timeout, a truncated
        response) costs that page's corroboration and nothing else — the whole point of a
        witness is to be there for the OTHER pages when one page goes missing.

        Returns records shaped like `provenance.build_positioned_index`'s output, but built
        directly rather than routed through it: that function derives `region` from an
        `unstructured` element `type` ("Table" -> "table", else "narrative"), and neither
        reading applies to a whole-page transcription, which is exactly why `region` here is
        the third value, "page_image" — so a resolver can tell a page-pixel witness apart
        from either half of the ordinary text layer.
        """
        if not manifest:
            return []
        pages = manifest.get("pages") or []
        if not pages:
            return []
        if not os.getenv("VISION_LLM_BASE_URL"):
            return []

        from doc_tools.baml_client.sync_client import b
        from baml_py import Image
        prompt = self._get_dynamic_prompt(
            prompt_name="sustainment_transcribe_page",
            fallback_file="prompts/sustainment_transcribe_page.md",
        )

        witness: List[dict] = []
        for entry in pages:
            page_no = entry.get("page")
            try:
                url = entry.get("s3_url")
                media, b64 = _fetch_image_b64(s3_client, url)
                if not b64:
                    continue
                img = Image.from_base64(media, b64)
                opts, _collector = _vision_call_opts()
                text = b.TranscribePage(page_image=img, system_instructions=prompt,
                                        baml_options=opts)
            except Exception as e:  # noqa: BLE001 — one bad page must not lose the others
                print(f"[SustainmentPlugin] TranscribePage failed on page {page_no}: {e} — "
                      f"this page will not corroborate any header value")
                continue
            witness.append({
                "element_id": f"page_ocr_{page_no}",
                "type": "PageTranscription",
                "region": "page_image",
                "page_number": page_no,
                "bbox": None,
                "page_width": entry.get("width"),
                "page_height": entry.get("height"),
                "text": text or "",
                "text_as_html": "",
            })
        return witness

    def _apply_vision_stats(self, ps: dict, n_tables: int, reasons: List[str],
                            doc_flags: List[str]) -> bool:
        """Turn one vision pass's per-crop counters into reviewer-facing reasons (and,
        where warranted, the doc_flags banner). Extracted so this logic exists exactly
        ONCE: both the normal table-crop path and the router's text-only path (item 2,
        PCN24-029 — a document with no Table element but part-shaped prose) run vision and
        both need the SAME post-hoc accounting; before this method they would otherwise
        have to duplicate it or drift apart.

        Returns whether these counters force needs_review; the caller ORs it into its own
        running flag rather than this method setting it directly, because callers also
        have OTHER reasons (a header failure, an unclassifiable doc_type) to set it.
        """
        needs_review = False
        if ps.get("crops_failed"):
            trunc = ps.get("crops_truncated") or 0
            cause = (f"{trunc} of them hit the {VISION_MAX_TOKENS}-token output bound "
                     f"(the model did not converge on a dense table)" if trunc
                     else "e.g. vision timeout")
            msg = (f"{ps['crops_failed']}/{n_tables} table crops failed "
                   f"({cause}) — extracted parts are likely INCOMPLETE")
            reasons.append(msg)
            # THE reviewer-facing case: a partial parts list is indistinguishable from
            # a complete one unless we say so. Parts MISSING here get no disposition
            # and nobody would know.
            doc_flags.append(f"PARTS MAY BE MISSING: {msg}")
            needs_review = True
        # Deliberately NOT a doc_flag: nothing is known to be missing here,
        # and "PARTS MAY BE MISSING" on a complete extraction would train
        # reviewers to ignore the banner that means it. This is a flag for
        # us — the cap needs raising before a document of this shape loses
        # rows — so it sets needs_review and says why, without claiming loss.
        if ps.get("crops_near_cap"):
            reasons.append(
                f"{ps['crops_near_cap']}/{n_tables} table crops emitted "
                f">={VISION_NEAR_CAP_RATIO:.0%} of the {VISION_MAX_TOKENS}-token output "
                f"bound — parts appear COMPLETE, but this corpus is approaching the cap "
                f"and a denser table would truncate silently")
            needs_review = True
        # ROW-SHORT — a DIFFERENT class from both of the above, and it gets a DIFFERENT
        # treatment on purpose. crops_failed means a crop produced no usable result at
        # all; this means a crop completed cleanly, raised nothing, and STILL returned
        # fewer rows than tier 1 counted on the same page (the SYTX9-122HP-1+ shape on
        # PCN23-002: dropped silently, nothing in crops_failed or crops_truncated). The
        # banner (doc_flags -> "PARTS MAY BE MISSING") is reserved for the FAILED case;
        # spending it on every row-count disagreement as well would blunt the one signal
        # reviewers are trained to stop and act on. So this sets needs_review and states
        # exactly what disagreed, in review_reasons, without claiming a banner-worthy loss.
        if ps.get("crops_row_short"):
            for d in ps.get("row_short_detail") or []:
                # "on this page", NOT "in this table": tier1_rows is one declined grid's
                # count, but vision_rows is the page TOTAL across every crop that landed
                # there. On a page carrying two declined tables the two numbers are not
                # measuring the same span, and the comparison is deliberately the
                # conservative direction — it under-reports (a page whose total clears the
                # largest single table's count never flags, even if a smaller table on it
                # lost rows) rather than inventing a shortfall. Say what is actually being
                # compared so a reviewer reading this line is not told a table lost rows
                # when what disagreed was a page.
                reasons.append(
                    f"page {d['page_number']}: tier 1's text layer saw {d['tier1_rows']} "
                    f"MPN-bearing row(s) in a table it could not parse, vision returned "
                    f"{d['vision_rows']} row(s) for that page — at least "
                    f"{d['tier1_rows'] - d['vision_rows']} row(s) may be missing")
            needs_review = True
        return needs_review

    def _apply_text_layer_stats(self, text_layer_assessment: dict, reasons: List[str],
                                doc_flags: List[str]) -> bool:
        """Turn ONE `text_layer_health.assess_elements` result into a reviewer-facing
        reason. Deliberately given the SAME treatment as `crops_near_cap` above, and for
        the same reason: nothing here is KNOWN to be missing, so this never earns the
        doc_flags banner. What a degraded text layer (TYC-PCN-24-210412: worst judged
        ligature retention 0.128, the font drops the `ti` pair) actually does is
        different from — and more dangerous than — the crops_failed case doc_flags
        exists for: a failed crop is visibly absent, but a dropped ligature produces a
        DIFFERENT, well-formed, plausible string with entirely correct provenance in its
        place. Nothing downstream can tell a misread value from a correct one by looking
        at it; only the second witness (the page-image transcription gated on this same
        assessment, and the parts-side corroboration check that follows it) can catch the
        ones it happens to corroborate, and an uncorroborated miss is not proof the rest
        of the document is clean. So this sets needs_review and says what is actually
        known — a MISREAD risk on every verbatim value from this document — rather than
        folding into the narrower, witness-gated doc_flags banner, which would both
        overclaim (it only checks parts that were actually witnessed) and train reviewers
        to stop trusting doc_flags on documents where nothing was ever proven missing.

        Returns whether this forces needs_review, same calling convention as
        `_apply_vision_stats`.
        """
        if not text_layer_assessment["text_layer_degraded"]:
            return False
        reasons.append(
            f"text layer degraded (worst judged ligature retention "
            f"{text_layer_assessment['text_layer_retention']}, threshold "
            f"{text_layer_health.DEGRADED_THRESHOLD}): verbatim values read from this "
            f"document's text layer — part numbers, dates, manufacturer names — may be "
            f"MISREAD, not missing. The extraction can silently substitute a different, "
            f"well-formed string for what is actually printed; treat every value from "
            f"this document as unverified until checked against the PDF")
        return True

    def process_fulltext(self, full_text: str, doc_id: str, metadata: Dict[str, Any] = None,
                         elements: List[Dict[str, Any]] = None, manifest: Dict[str, Any] = None,
                         s3_client: Any = None, bucket: str = None) -> List[DocumentNode]:
        # v4 extraction-trace JOIN (ADR-0038): open the trace on doc_id via
        # create_trace_id(seed=doc_id), so THIS extraction and the downstream review (which
        # seeds on the same doc_id it reads from review.json.trace_id) land ONE unified trace —
        # bucket -> extraction -> review. The header/parts @traced passes nest as child spans;
        # the end set_trace_standard enriches. Fail-soft: observed_trace never blocks extraction.
        #
        # RE-RUNS APPEND TO THE SAME TRACE — BY DESIGN, AND IT LOOKS LIKE DATA LOSS.
        # The seed is the doc_id, so the langfuse trace id is DETERMINISTIC per document:
        # re-extracting the same doc does not create a new trace, it adds spans to the
        # existing one. In the Langfuse UI a trace is timestamped by its FIRST observation,
        # so a re-run never floats to the top of a recency-sorted list — it silently thickens
        # a trace dated whenever that doc was first processed. Cost a full afternoon on
        # 2026-08-06: SDK version, dependency locks, worker uptime and the ingestion pipeline
        # were all investigated for "missing traces" that were never missing.
        # TO FIND A RE-RUN: search by the seeded trace id (create_trace_id(seed=doc_id)) or by
        # the doc, NOT by recency.
        # IF YOU EVER WANT ONE TRACE PER RUN: the lever is the seed (e.g. f"{doc_id}:{run_id}"),
        # but that BREAKS the review join above unless the review seeds identically — it
        # re-derives from review.json.trace_id. Prefer tagging/naming spans per run so runs stay
        # separable INSIDE the unified trace; the join is the reason this seed exists.
        # First-use validation: raises PromptUnavailableError (loudly, naming every
        # missing file) before any per-document work starts, rather than letting a
        # missing prompt surface lazily inside a broad per-document except clause.
        self._ensure_prompts_available()
        with observed_trace(MAPPING, {"request_key": doc_id}, name="sustainment extraction"):
            return self._extract_fulltext(full_text, doc_id, metadata=metadata, elements=elements,
                                          manifest=manifest, s3_client=s3_client, bucket=bucket)

    def _extract_fulltext(self, full_text: str, doc_id: str, metadata: Dict[str, Any] = None,
                          elements: List[Dict[str, Any]] = None, manifest: Dict[str, Any] = None,
                          s3_client: Any = None, bucket: str = None) -> List[DocumentNode]:
        index = provenance.build_positioned_index(elements)
        # MEASURED against this SAME index, not the raw elements: a damaged text layer
        # (TYC-PCN-24-210412's dropped `ti` ligature) is a property of the text this
        # document's extraction actually produced, and the positioned index is what every
        # downstream verbatim check (including the witness gate below) reads against.
        text_layer_assessment = text_layer_health.assess_elements(elements)
        ocr_norm = provenance._norm(full_text)
        stats = {"n_tables": 0, "n_crops_used": 0, "crops_missing": 0, "crops_failed": 0,
                 "crops_truncated": 0, "crops_near_cap": 0, "crops_row_short": 0,
                 "vision_used": False, "grid_forwarded": 0, "grid_label_failed": 0,
                 "grid_rows_emitted": 0, "grid_no_parts_col": 0,
                 "text_layer_repairs": 0, "text_layer_repair_detail": []}
        stats["text_layer_degraded"] = text_layer_assessment["text_layer_degraded"]
        stats["text_layer_retention"] = text_layer_assessment["text_layer_retention"]
        stats["text_layer_detail"] = text_layer_assessment["text_layer_detail"]
        reasons: List[str] = []
        needs_review = False
        # The doc-level reasons that FORCE review — i.e. the extraction telling us its own
        # output is not fully trustworthy (header failed, a vision crop timed out, parts pass
        # died). These MUST REACH THE REVIEWER: if a review proceeds on degraded extraction,
        # the human deciding dispositions has to see the degradation, or a partial parts list
        # reads as a complete one. `reasons` keeps EVERYTHING for the record (advisory notes,
        # per-item detail); this is the reviewer-facing subset. Live case: Diodes PCN 2683 —
        # "2/5 table crops failed, extracted parts are likely INCOMPLETE" was recorded and
        # then reached nobody, because nothing downstream carried review_reasons at all.
        doc_flags: List[str] = []

        # DEGRADED TEXT LAYER: recorded HERE, right where the assessment lands, so it
        # covers every verbatim read this method goes on to do — see
        # `_apply_text_layer_stats` for why this gets needs_review but never doc_flags.
        if self._apply_text_layer_stats(text_layer_assessment, reasons, doc_flags):
            needs_review = True

        # ---- Pass 1: header (text-only, gpt-oss) ----
        header = None
        try:
            header = self._extract_header(full_text)
        except PromptUnavailableError:
            # A missing prompt file is a CONFIGURATION defect, not a per-document
            # extraction failure — it affects every document identically and no
            # retry fixes it. The broad `except Exception` below exists to degrade
            # a genuine per-document failure (a vision timeout, a bad response); it
            # must not also absorb this, or a deployment error silently looks like
            # a normal 0-parts run. See doc_tools/plugins/base.py::PromptUnavailableError.
            raise
        except Exception as e:  # noqa: BLE001
            reasons.append(f"header pass failed: {e}")
            doc_flags.append(f"header extraction failed: {e}")
            needs_review = True
        header_d = header_to_dict(header) if header is not None else empty_header(doc_id)
        if not header_d.get("doc_id"):
            header_d["doc_id"] = doc_id
        # ONE authoritative, key-safe doc_id. Both sources are messy — the LLM's
        # 'as printed' number (spaces / '#') or a path-derived fallback — and
        # doc_id is a KEY for the workflow id, the MinIO prefix, the graph IRI and
        # the provenance index. Normalize HERE so every downstream consumer keys
        # on the SAME clean slug; stash the raw printed form for faithful display.
        header_d["doc_id_raw"] = header_d.get("doc_id")
        header_d["doc_id"] = norm.normalize_doc_id(header_d.get("doc_id"))
        # doc_type is derived from the DOCUMENT'S OWN TITLE, not from the header model's
        # `doc_type` field: that field flipped PCN/PDN/PCN across repeated fires on
        # byte-identical input (see HEADER_TEMPERATURE's comment above and the module
        # docstring of `sustainment_header_trust`). A vendor's title is printed once and
        # does not sample. `header_to_dict` still normalizes the model's raw label via
        # `norm.normalize_doc_type` — that normalization is harmless and kept for the
        # `header_d["doc_type"]` slot's default shape — but the plugin OVERRIDES it right
        # here, and the model's own label survives only inside the reason text below when
        # it is not used, never as the value actually routed on.
        derived, dt_source = header_trust.doc_type_from_titles(
            header_trust.titles_from_elements(elements))
        if derived:
            header_d["doc_type"] = derived
            header_d["doc_type_source"] = dt_source
        else:
            # No usable title evidence (or the title itself disagrees with itself — an
            # explicit code alongside the opposite keyword class). Keep the existing
            # routing default of PCN, but say so explicitly and KEEP forcing review:
            # doc_type SELECTS THE DISPOSITION RULESET, so a defaulted value is a real
            # risk to whoever reviews this notice, not a cosmetic gap.
            raw_label = getattr(header, "doc_type", None) if header is not None else None
            model_label = getattr(raw_label, "value", raw_label)  # unwrap the DocType enum
            evidence_desc = {"title-ambiguous": "ambiguous",
                             "no-title-evidence": "none"}.get(dt_source, dt_source)
            header_d["doc_type"] = "PCN"
            header_d["doc_type_source"] = dt_source
            reasons.append(
                f"doc_type not derivable from the document title (title evidence "
                f"{evidence_desc}; the header pass said {model_label!r}, not used) "
                f"— defaulted to PCN"
            )
            doc_flags.append("notice type could not be classified — defaulted to PCN "
                             "(dispositions proposed under PCN rules may be wrong)")
            needs_review = True

        # Refuse any header value (mfr / pub_date / doc_level_ltb_date) that is not
        # verbatim in the document, and do it HERE — as soon as the header dict is final.
        #
        # Two ordering constraints, and this is the only point that satisfies both:
        #   AFTER `index` (built at the top of this method), because "verbatim in the
        #   document" is decided against the positioned index and nothing else.
        #   BEFORE `reconcile_ltb` below, because that BACKFILLS every part lacking its own
        #   LTB date from `header_d["doc_level_ltb_date"]`. Refusing the header field after
        #   that point would null the header's copy while leaving the refused date written
        #   onto every part that inherited it — an unsourced value surviving in the data
        #   after the field it came from was rejected, which is precisely the defect the
        #   refusal exists to prevent, one hop further out.
        #
        # It is also before `build_review_items`, so a refused field produces NO review
        # item rather than a review item for a value already dropped.
        #
        # THE SECOND WITNESS is built HERE, gated on the SAME `text_layer_assessment`
        # computed at the top of this method against this document's `index` — never
        # unconditionally: an ungated witness would be a standing second chance for every
        # fabrication to be ratified by a noisy transcription (see
        # sustainment_header_trust's module docstring). A healthy document never pays for
        # a page-image vision call at all.
        witness_index = None
        if text_layer_assessment["text_layer_degraded"]:
            witness_index = self._transcribe_pages_witness(manifest, s3_client)
        stats["witness_pages"] = len(witness_index) if witness_index else 0
        # `text_layer_degraded` is passed SEPARATELY from `witness_index` and is not
        # inferrable from it: the three no-witness paths above (no VISION_LLM_BASE_URL, no
        # page manifest, a transcription that failed) all hand the refusal a None witness
        # on a document that IS degraded, which would otherwise be indistinguishable from a
        # healthy one. The refusal uses it to switch OFF reading a manufacturer's name out
        # of the document's own headings — a damaged text layer cannot be trusted to spell
        # one (`TE Connecvity`).
        reasons += header_trust.refuse_unsourced_header_values(
            header_d, index, witness_index=witness_index,
            text_layer_degraded=text_layer_assessment["text_layer_degraded"])

        # Level-2 dedupe identity (doc_tools/utils/notice_identity.py): a deterministic
        # (mfr, doc_id, revision) key computed HERE, at the header pass, because that is
        # the only place it CAN be computed — a sensor sees an S3 object, not a header,
        # and the key needs the (possibly refused-and-nulled) header fields above. Put on
        # `stats` (and, via `review` below, into review.json) so the ingress-user lane
        # that owns dedupe can compare two arrivals without re-running extraction.
        # `build_identity` — not `notice_key` directly — because it ALSO decides whether
        # a key can be formed at all: a failed or partial header (mfr and/or doc_id
        # missing) must still ingest, so this never raises, and represents the key as
        # absent (key=None, `note` says why) rather than building a key out of empty
        # strings that would collide every failed document with every other.
        #
        # CONSEQUENCE, stated so it is not discovered as a surprise: because this runs
        # AFTER refuse_unsourced_header_values, a notice whose `mfr` was REFUSED (no
        # citation for the printed value) ends up with no dedupe key and is therefore
        # never matched against anything. That is the deliberate direction — declining to
        # key costs a missed duplicate, which the next arrival can still be compared
        # against once its own header is sourced; keying on a refused value costs a FALSE
        # match, which silently merges two different manufacturers' notices. Coverage is
        # currently total anyway: at pin 025be04a all nine corpus notices carry both an
        # mfr and a doc_id, with refusals 0.
        stats["notice_identity"] = notice_identity.build_identity(
            header_d.get("mfr"), header_d.get("doc_id"), header_d.get("revision"))

        # ---- Router + Pass 2: parts (multimodal, Gemma) ----
        tables = provenance.table_elements(elements)
        stats["n_tables"] = len(tables)
        parts_d: List[dict] = []
        vision_ok = bool(os.getenv("VISION_LLM_BASE_URL"))
        # TIER 1 — the text layer, when the document has one. Deterministic, sub-second,
        # exact MPNs, per-cell provenance. Vision is the FALLBACK for scans; it is not the
        # default for text that is already machine-readable.
        tl_parts, tl_stats = self._extract_parts_text_layer(manifest, s3_client, bucket)
        stats.update(tl_stats)
        # tl_stats["text_layer_declines"] carries each decline's full `grid` (spec item 1) so
        # tier 2 can forward it verbatim instead of re-reading a crop. That grid must NOT ride
        # into `stats["text_layer_declines"]`: `stats` is persisted into extraction.json / the
        # review payload, and scripts/pcn_corpus_run.py reads that file as a corpus manifest —
        # embedding every declined table's full grid there would bloat it for no reader. Keep
        # the grid-bearing list local (tl_declines_with_grid) and hand THAT to _extract_parts;
        # what lands in `stats` is the same list with `grid` projected out.
        tl_declines_with_grid = tl_stats.get("text_layer_declines") or []
        stats["text_layer_declines"] = [
            {k: v for k, v in d.items() if k != "grid"} for d in tl_declines_with_grid
        ]
        if tl_parts:
            parts_d = tl_parts
        elif tables and vision_ok and s3_client is not None:
            try:
                parts_d, ps = self._extract_parts(tables, manifest, s3_client, full_text,
                                                  tl_declines_with_grid)
                stats.update(ps)
                stats["vision_used"] = True
                if self._apply_vision_stats(ps, len(tables), reasons, doc_flags):
                    needs_review = True
            except PromptUnavailableError:
                # See the comment on the header pass's identical clause above.
                raise
            except Exception as e:  # noqa: BLE001
                reasons.append(f"parts pass failed: {e}")
                doc_flags.append(f"PARTS MAY BE MISSING: the parts pass failed ({e})")
                needs_review = True
        elif tables and not vision_ok:
            reasons.append("tables present but VISION_LLM_BASE_URL unset — parts NOT extracted")
            doc_flags.append("PARTS NOT EXTRACTED: this document has parts tables but the vision "
                             "model was unavailable")
            needs_review = True
        elif not tables and vision_ok and s3_client is not None and _has_part_shaped_text(full_text):
            # THE PCN24-029 SHAPE (see _has_part_shaped_text above): a single MPN under
            # "MODELS AFFECTED" with no table at all, so unstructured detected zero Table
            # elements and the ordinary branches above never fire. Route to vision on the
            # text alone rather than silently taking the header-only path below.
            try:
                # A SYNTHETIC element, not a real Table one — there is no crop to point
                # at, because unstructured never detected a table to crop. With no
                # `metadata`, provenance.resolve_element_image returns None inside
                # _extract_parts and its EXISTING `missing += 1` branch already handles
                # that shape correctly: OCR + HTML only, no image. That degraded shape is
                # the INTENDED outcome of this path, not a bug tripping the missing-image
                # counter — there was never an image to have.
                synthetic = [{"text": full_text, "metadata": {}}]
                parts_d, ps = self._extract_parts(synthetic, manifest, s3_client, full_text,
                                                  tl_declines_with_grid)
                stats.update(ps)
                stats["vision_used"] = True
                stats["router_textonly_vision"] = True
                reasons.append("no Table element detected, but the text names an affected-parts "
                               "section and carries an MPN-shaped token — routed to vision on the "
                               "text alone (no crop image available)")
                if self._apply_vision_stats(ps, len(synthetic), reasons, doc_flags):
                    needs_review = True
            except PromptUnavailableError:
                # See the comment on the header pass's identical clause above.
                raise
            except Exception as e:  # noqa: BLE001
                reasons.append(f"parts pass failed: {e}")
                doc_flags.append(f"PARTS MAY BE MISSING: the parts pass failed ({e})")
                needs_review = True
        elif not tables:
            # No table detected -> header-only. Instrumented so the borderless
            # miss-rate is visible (Phase 0 decision #3: build the coordinate
            # page-crop fallback only if this fires on parts-bearing docs).
            reasons.append("no Table element detected — parts pass skipped (header-only)")

        # De-quote the VALUES, whichever tier produced them — applied after the tiers
        # converge and BEFORE dedup, so a quoted and an unquoted copy of the same part
        # collapse into one row instead of surviving as two.
        n_dequoted = dequote_parts(parts_d)
        if n_dequoted:
            stats["parts_dequoted"] = n_dequoted

        # dedup across crops, then reconcile per-part LTB (per-row primary,
        # doc-level fallback)
        parts_d = clean_replacements(
            reconcile_ltb(dedup_parts(parts_d), header_d.get("doc_level_ltb_date")))

        # THE SECOND WITNESS, PARTS SIDE. The header check above can afford to drop an
        # unsupported value; this one deliberately cannot. Tier 1 reads MPNs straight out
        # of the text layer, so a dropped ligature does not produce a missing part — it
        # produces a DIFFERENT, well-formed, plausible MPN carrying entirely correct
        # per-cell provenance, and nothing downstream has any way to notice. 898 becomes
        # 897 with every check green. Only the pixels disagree, so the pixels get asked.
        #
        # It RAISES THE ROW rather than editing it: the corpus is scored on parts, and
        # rewriting an MPN on the strength of a vision transcription would put that score
        # at the mercy of the noisiest reader in the pipeline (see the function's
        # docstring). No witness means no findings — an absent witness is not evidence.
        uncorroborated = text_layer_health.uncorroborated_parts(parts_d, witness_index)
        stats["parts_uncorroborated"] = len(uncorroborated)
        stats["parts_uncorroborated_detail"] = uncorroborated
        if uncorroborated:
            listed = ", ".join(
                f"{u['field']}={u['mpn']!r} (p{u['page_number']})" for u in uncorroborated[:5])
            more = f" and {len(uncorroborated) - 5} more" if len(uncorroborated) > 5 else ""
            reasons.append(
                f"{len(uncorroborated)} part value(s) read from this document's DEGRADED text "
                f"layer are not corroborated by the page image: {listed}{more}")
            doc_flags.append(
                f"PART NUMBERS MAY BE MISREAD: this document's text layer is damaged "
                f"(retention {text_layer_assessment['text_layer_retention']}), and "
                f"{len(uncorroborated)} extracted part value(s) do not appear in the page "
                f"image — verify them against the PDF before use")
            needs_review = True

        # ---- Validation + review payload ----
        items, item_reasons = build_review_items(header_d, parts_d, index, ocr_norm)
        reasons += item_reasons
        cnt = validate_count(header_d, len(parts_d))
        if cnt:
            # INFORMATIONAL ONLY — deliberately does NOT set needs_review.
            # This cross-check reads the LLM-GENERATED summary, so its input varies run to
            # run for the SAME document: onsemi PD26044X1 reviewed fine once, then failed
            # later with nothing about the document changed. A gate whose input is
            # nondeterministic produces FLAKY refusals, and its two observed firings in
            # production were BOTH false positives (a part number's digits, then a year).
            # So it degrades to a note a human can read in review_reasons, never a flag.
            # A real under-extraction check wants a DETERMINISTIC reference — extracted rows
            # vs the parts TABLE's row count (structure vs structure), not prose vs structure.
            reasons.append(cnt)
        # `or reasons` REMOVED (2026-07-29): it promoted EVERY diagnostic — including notes the
        # code deliberately declines to flag on (the "no Table element detected" instrumentation
        # above explicitly sets no flag, then this line set it anyway) — into a doc-level review
        # flag, which downstream becomes a HARD REFUSAL. "We noted something" is not "a human must
        # review this"; conflating them made the file contradict its own stated intent and turned
        # one misparsed number into a refused notice (Qorvo 23-0171). Every review-forcing
        # condition now says so AT ITS OWN SITE; `reasons` stays the full, honest narrative
        # surfaced as review_reasons.
        if any(it["needs_review"] for it in items):
            needs_review = True

        # Telemetry (ADR-0038): project the extraction's provenance onto the trace
        # `traced` opened above — identity keyed on doc_id, honest-degradation as
        # scores (needs_review, crops_failed/n_tables). No-op when Langfuse is off;
        # emission never blocks the extraction (fail-soft-and-counted in the leaf).
        set_trace_standard(MAPPING, build_trace_values(
            doc_id=doc_id, header_d=header_d, stats=stats,
            needs_review=needs_review, domain=self.domain_type,
            prompt_refs=self.prompt_refs,
        ))

        review = {"doc_id": header_d.get("doc_id") or doc_id,
                  # PROVENANCE — the extractor that PRODUCED this artifact (ADR-0034).
                  #
                  # WHY IT LIVES IN THE ARTIFACT AND NOT IN THE READER'S ENVIRONMENT. The trust
                  # table is keyed on (vendor-format x pipeline_version) precisely so a rung
                  # earned under one extractor does not survive that extractor changing. The
                  # consumer side implemented that second component as an env var read at
                  # PROCESSING time — which describes the reader's deployment, not this
                  # artifact's producer. Re-drive a notice extracted last week on a sensor
                  # deployed today and it inherits today's version: an old extraction wearing a
                  # new extractor's trust, which inverts the guard's purpose.
                  #
                  # pipeline_version is PRODUCER-SIDE PROVENANCE, so it is stamped HERE, once, by
                  # the thing it describes — the same category as `requested_by` naming who
                  # actually decided rather than whoever happened to be running.
                  #
                  # Baked at container build (`DOC_TOOLS_VERSION` build-arg), never a deploy-time
                  # env var: the consumer's env-var attempt was UNSET on every pod, so its whole
                  # trust axis collapsed to one value. A sentinel default keeps an unstamped
                  # image visible in the corpus instead of plausible.
                  "pipeline_version": os.getenv("DOC_TOOLS_VERSION", "doc-tools@unstamped"),
                  # trace_id links this review.json to the extraction trace above:
                  # the sensor forwards it as X-Trace-Id so start_review joins the
                  # same trace (one trace: bucket -> extraction -> review -> queue).
                  # doc_id (the INPUT key), NOT the model-extracted header doc_id: it is the
                  # SAME seed process_fulltext opened observed_trace on, so the review composition
                  # (which seeds create_trace_id on this value) unifies with the extraction trace.
                  "trace_id": doc_id,
                  # the raw printed notice number ('PCN # 23-002') for DISPLAY;
                  # doc_id above is the normalized key. Display may prefer this.
                  "doc_id_raw": header_d.get("doc_id_raw") or header_d.get("doc_id") or doc_id,
                  # doc_type + categories DRIVE the disposition proposer's rule match:
                  # every PCN rule requires a change category, so without these the
                  # proposer returns UNCLASSIFIABLE for every part and the UI shows
                  # 'needs a disposition' on all of them. review.json is the sensor's
                  # ONLY source for the start_review payload (the graph drops per-part
                  # needs_review), so these MUST live here, not only in the graph.
                  # Categories stringified to their enum values (== the ruleset's
                  # pcn:changeClass category keys: 'Material','Process',…).
                  "doc_type": header_d.get("doc_type") or "PCN",
                  # ATTESTATION, not a second copy of the value (ADR-0034 normalization).
                  #
                  # `doc_type` above DEFAULTS to "PCN" when the header pass extracted none — which
                  # makes "identified as a PCN" and "we did not know" the SAME VALUE downstream.
                  # That collision is why the trust key's doc_type segment could not be guarded:
                  # a check cannot separate identified from defaulted when both read `PCN`.
                  #
                  # Emitted as a SEPARATE provenance-bearing field rather than by changing
                  # `doc_type` to a sentinel, because `doc_type` DRIVES THE DISPOSITION PROPOSER
                  # (every PCN rule requires a change category keyed on it) — a sentinel there
                  # would turn every unextracted notice UNCLASSIFIABLE. Same shape as
                  # `review_state_source`: the classification field keeps its usable value, and a
                  # provenance field says where that value came from.
                  #
                  # The value now comes from the DOCUMENT'S OWN TITLE TEXT (see
                  # `sustainment_header_trust.doc_type_from_titles`), not from the header
                  # model's label — that label flipped PCN/PDN/PCN across repeated fires on
                  # identical input, so it is no longer trusted for routing. `header_d`
                  # carries the ACTUAL provenance of the value that landed in `doc_type` as
                  # `doc_type_source`: "title" (unambiguous title evidence), "title-ambiguous"
                  # (the title contradicts itself), or "no-title-evidence" (nothing to derive
                  # from). "extraction" is no longer a possible value for this field — there
                  # is no longer any path that trusts the model's raw label enough to attest
                  # to it. `empty_header` (the `header is None` path) sets no `doc_type_source`
                  # key at all, which the `or "defaulted"` fallback below covers the same way
                  # it always covered a missing value.
                  "doc_type_source": header_d.get("doc_type_source") or "defaulted",
                  "categories": [str(getattr(c, "value", c))
                                 for c in (header_d.get("categories") or [])],
                  # EXTRACTION-QUALITY WARNINGS the reviewer must see (the doc-level reasons
                  # that forced review). Distinct from `review_reasons`, which is the complete
                  # record including advisory notes and per-item detail — those either aren't
                  # trustworthy enough to act on (the count cross-check) or are already visible
                  # per row (the needs_review badge). If a review proceeds on degraded
                  # extraction, THIS is what tells the human so.
                  "doc_review_reasons": doc_flags,
                  "review_items": items,
                  # Level-2 dedupe identity (see the `stats["notice_identity"]` comment
                  # above, where this is computed) — same dict, duplicated onto the review
                  # payload because review.json, not extraction.json, is the sensor's
                  # documented contract for this lane (see the pipeline_version comment
                  # above this block for the same pattern: producer-side data belongs on
                  # the artifact a consumer actually reads).
                  "notice_identity": stats["notice_identity"],
                  # page rasters for the viewer are Phase 5.8 (needs a renderer);
                  # the data contract carries the field now, populated later.
                  "pages": []}

        notice = SustainmentNotice(
            doc_id=header_d.get("doc_id") or doc_id,
            doc_type=header_d.get("doc_type") or "PCN",
            revision=header_d.get("revision"),
            pub_date=header_d.get("pub_date") or "",
            mfr=header_d.get("mfr") or "",
            mfr_parent=header_d.get("mfr_parent"),
            categories=header_d.get("categories") or [],
            summary=header_d.get("summary") or "",
            doc_level_ltb_date=header_d.get("doc_level_ltb_date"),
            impacted_parts=[PartImpact(**p) for p in parts_d],
        )
        aug = SustainmentAugmentation(notice=notice, review=review, needs_review=needs_review,
                                      review_reasons=reasons, stats=stats)
        section = BaseSection(title="Sustainment Notice", level=0, page_start=0,
                              content="", node_id=doc_id)
        return [DocumentNode(base_extraction=section, domain_augmentation=aug)]

    def augment(self, section: BaseSection, config: Any = None) -> DocumentNode:
        # Sustainment is processed globally via process_fulltext; per-chunk augment is a no-op.
        return DocumentNode(base_extraction=section, domain_augmentation=None)

    def to_graph_queries(self, nodes: List[DocumentNode], config: Any, doc_id: str = "",
                         image_prefix: str = "") -> Tuple[List[str], List[str]]:
        cypher_queries: List[dict] = []
        sparql_queries: List[str] = []

        for node in nodes:
            sec = node.base_extraction
            aug = node.domain_augmentation
            if not isinstance(aug, SustainmentAugmentation):
                continue
            notice = aug.notice
            section_id = sec.node_id or f"section_{sec.page_start}_{sec.title}"

            cypher_queries.append({
                "query": f"""
                MERGE (p:{config.graph_node_label}:{self.domain_label} {{id: $section_id}})
                SET p.title = $title
                """,
                "params": {"section_id": section_id, "title": sec.title},
            })

            edge_cypher = f"""
            MERGE (p:{config.graph_node_label}:{self.domain_label} {{id: $section_id}})
            MERGE (n:SustainmentNotice:{self.domain_label} {{id: $notice_id}})
            SET n.pub_date = $pub_date, n.mfr = $mfr, n.mfr_parent = $mfr_parent,
                n.type = $doc_type,
                n.revision = $revision, n.doc_level_ltb_date = $doc_level_ltb_date,
                n.needs_review = $needs_review
            MERGE (p)-[:GOVERNED_BY]->(n)

            WITH n
            UNWIND $impacted_parts AS part
            MERGE (c:Component:{self.domain_label} {{mpn: part.affected_mpn}})
            MERGE (c)-[:SUBJECT_TO]->(n)

            WITH n, c, part
            FOREACH (r IN CASE WHEN part.replacement_mpn IS NOT NULL AND part.replacement_mpn <> "" THEN [1] ELSE [] END |
                MERGE (alt:Component:{self.domain_label} {{mpn: part.replacement_mpn}})
                MERGE (c)-[:REPLACED_BY {{ltb_date: part.ltb_date}}]->(alt)
            )
            """
            parts_params = [
                {"affected_mpn": p.affected_mpn, "replacement_mpn": p.replacement_mpn,
                 "ltb_date": p.ltb_date}
                for p in notice.impacted_parts
            ]
            cypher_queries.append({
                "query": edge_cypher,
                "params": {
                    "section_id": section_id, "notice_id": notice.doc_id,
                    "pub_date": notice.pub_date, "mfr": notice.mfr,
                    # "" not None: the graph stores the brand-vs-owner pair as two
                    # properties, and a Cypher null would DROP the property entirely,
                    # making "no parent printed" and "never extracted" the same absence.
                    "mfr_parent": notice.mfr_parent or "",
                    "doc_type": notice.doc_type, "revision": notice.revision or "",
                    "doc_level_ltb_date": notice.doc_level_ltb_date or "",
                    "needs_review": aug.needs_review, "impacted_parts": parts_params,
                },
            })

            # --- JENA SPARQL/RDF ---
            # notice.doc_id is already normalized at finalization; normalize again
            # here (idempotent) so the graph IRI keys on the SAME canonical slug as
            # review.json / the workflow id. (safe_mpn below stays a bare space->_
            # replace — MPNs keep '#' reel codes verbatim as provenance join keys.)
            safe_notice_id = norm.normalize_doc_id(notice.doc_id)
            if str(notice.doc_type).upper() == "PDN":
                notice_class = "pcn:ProductDiscontinuationNotice"
            else:
                notice_class = "pcn:ProcessChangeNotification"

            # Scope instance data to the domain's INSTANCE graph, NOT the vocabulary graph.
            # Two reasons, one invariant: (1) an unscoped INSERT DATA lands in Jena's DEFAULT
            # graph where the mesh can't see it (the graph-name/semantic-domain seam); (2) the
            # vocabulary graph <http://internal/{DOMAIN}> is MANIFEST-reproducible and gets
            # DROP-first wiped on every prime re-ingest — runtime INSTANCE data is NOT
            # reproducible, so it must live in a graph prime never touches. Producers with
            # different reproducibility must not share a graph (AGENTS.md). domain_label ==
            # 'SUSTAINMENT' -> instances land in <http://internal/SUSTAINMENT_INSTANCES>, which
            # the pcn resolveInstance provider queries and clear_ontology_graphs never drops.
            graph_uri = f"http://internal/{self.domain_label}_INSTANCES"
            sparql = f"""
            PREFIX pcn: <http://internal/sustainment/pcn#>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

            INSERT DATA {{
              GRAPH <{graph_uri}> {{
                <http://internal/sustainment/doc/{safe_notice_id}> a {notice_class} .
            """
            for cat in notice.categories:
                safe_cat = str(cat).replace(' ', '_')
                sparql += f"""
                <http://internal/sustainment/doc/{safe_notice_id}> pcn:hasChangeCategory pcn:{safe_cat} .
                """
            for part in notice.impacted_parts:
                safe_mpn = part.affected_mpn.replace(' ', '_')
                sparql += f"""
                <http://internal/components/{safe_mpn}> pcn:subjectToNotice <http://internal/sustainment/doc/{safe_notice_id}> .
                """
                if part.ltb_date:
                    sparql += f"""
                    <http://internal/components/{safe_mpn}> pcn:hasLastTimeBuyDate "{escape_sparql_string(part.ltb_date)}"^^xsd:date .
                    """
                if part.replacement_mpn:
                    safe_rep = part.replacement_mpn.replace(' ', '_')
                    sparql += f"""
                    <http://internal/components/{safe_mpn}> pcn:hasReplacement <http://internal/components/{safe_rep}> .
                    """
            sparql += "  }\n}"  # close GRAPH, then INSERT DATA
            sparql_queries.append(sparql)

        return cypher_queries, sparql_queries
