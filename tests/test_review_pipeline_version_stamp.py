"""review.json must carry the EXTRACTOR'S OWN VERSION (ADR-0034 provenance stamp).

WHY THIS IS A CONTRACT AND NOT A NICE-TO-HAVE. Downstream, the trust table is keyed on
(vendor-format x pipeline_version) so that a rung earned under one extractor does NOT survive that
extractor changing. That guard only means something if the version names THE THING THAT PRODUCED
THE ARTIFACT.

The consumer side originally read it from an env var at PROCESSING time, which describes the
reader's deployment instead — re-drive a notice extracted last week on a sensor deployed today and
it inherits today's version: an old extraction wearing a new extractor's trust, which inverts the
guard. And that env var was UNSET on every pod in sandbox, so the whole second axis of the trust
key collapsed to a single value ("unset") and the guard was discriminating on a dimension with one
member.

So: producer-side, stamped once, by the thing it describes. This test is the seam's pin — if the
field stops being emitted, every promoted format silently stops matching and the pipeline degrades
to fully supervised. FAILING SAFE, AND THEREFORE INVISIBLY, which is the class that needs a red.
"""
from __future__ import annotations

import os
import re

import pytest

_FIELD = "pipeline_version"


def _review_assembly_source() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "doc_tools", "plugins", "sustainment.py"), encoding="utf-8") as fh:
        return fh.read()


def test_review_json_emits_pipeline_version():
    """The field is written into the review dict the plugin builds."""
    src = _review_assembly_source()
    assert f'"{_FIELD}"' in src, (
        "review.json no longer carries pipeline_version — every promoted format stops matching "
        "and the pipeline silently degrades to fully supervised"
    )


def test_version_comes_from_the_BAKED_image_identity_not_a_deploy_env():
    """Baked, not deploy-set — the distinction the consumer's failure already proved.

    `DOC_TOOLS_VERSION` is an image build-arg (see .github/workflows/build-container.yml), so an
    unstamped image is impossible to produce accidentally and obvious when produced deliberately.
    A deploy-time env var is exactly what failed: unset on every pod, silently.
    """
    src = _review_assembly_source()
    assert "DOC_TOOLS_VERSION" in src, "the version no longer reads the baked image identity"
    m = re.search(r'"pipeline_version":\s*os\.getenv\(\s*"DOC_TOOLS_VERSION"\s*,\s*"([^"]+)"', src)
    assert m, "pipeline_version is not sourced from the DOC_TOOLS_VERSION build-arg"
    default = m.group(1)
    assert "unstamped" in default, (
        f"the fallback {default!r} is plausible-looking; an unstamped image must be OBVIOUS in the "
        f"corpus, not blend in with real versions — a sentinel, never a guess"
    )


def test_the_writer_copies_the_plugin_dict_WHOLESALE():
    """THE HOP BETWEEN THE STAMP AND THE ARTIFACT, pinned.

    The plugin builds the `review` dict; a DIFFERENT module (`assets/semantic_assets.py`) is what
    actually writes it to S3. A field can therefore be stamped correctly and still never reach the
    artifact — which is precisely how the consumer side lost `review_state_source` and
    `extraction_warnings` at cortex-bff's `/reviews`: a hand-enumerating consumer silently dropped
    what its producer computed.

    The writer copies wholesale (`dict(aug0.review)`), so new plugin fields survive by construction.
    This pins that shape: if it ever becomes a hand-enumerated dict, `pipeline_version` disappears
    from the artifact, every promoted format stops matching, and the pipeline degrades to fully
    supervised — safely, and therefore invisibly.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "doc_tools", "assets", "semantic_assets.py"), encoding="utf-8") as fh:
        writer = fh.read()
    assert "dict(aug0.review)" in writer, (
        "the review writer no longer copies the plugin's dict wholesale — a hand-enumerated "
        "payload drops any field the enumerator forgets, which is how this exact class of bug "
        "reached production twice on the consumer side"
    )


def test_the_build_bakes_the_arg():
    """VERIFY-THE-PIPE: the code reading the env proves nothing if the build never sets it."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wf = os.path.join(here, ".github", "workflows", "build-container.yml")
    if not os.path.exists(wf):  # pragma: no cover
        pytest.skip("workflow not present in this checkout")
    with open(wf, encoding="utf-8") as fh:
        content = fh.read()
    assert "ARG DOC_TOOLS_VERSION" in content, "the Dockerfile never declares the build-arg"
    assert "ENV DOC_TOOLS_VERSION" in content, "the build-arg never becomes a runtime env"
    # MATCH THE PASS, NOT THE DEFAULT. The first version of this assertion looked for
    # "DOC_TOOLS_VERSION=doc-tools@" — which the ARG's own default line
    # (`ARG DOC_TOOLS_VERSION=doc-tools@unstamped`) satisfies. Deleting the build-args pass left
    # it GREEN: the guard was aimed one line off its subject and would have shipped an image
    # permanently stamped `unstamped` while claiming the pipe was verified. Caught by
    # break-on-purpose; pinned to the interpolation, which only the real pass contains.
    assert "DOC_TOOLS_VERSION=doc-tools@${{ github.sha }}" in content, (
        "the build never PASSES the sha — the image would ship the unstamped sentinel forever, "
        "which is the reachability gap one layer out from the code that reads it"
    )
