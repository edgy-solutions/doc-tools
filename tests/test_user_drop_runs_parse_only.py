"""The leaf ruling's item 4, pinned: *"before the title read, a pdf runs parse +
text layer only. The title read is the next step; parts extraction waits on its
leaf."* (architect, 2026-10-21)

Today that invariant HOLDS, and it holds for a reason worth keeping: the user-drop
parse asset takes only an S3 resource, so it has no model client to run an
extraction pass with. Nothing stated it and no test failed if it changed -- it fell
out of the downstream `origin_unresolved` short-circuit, which is tested elsewhere
(`test_ingress_user_stamp.py` section 6b) on the GRAPH asset, not on the parse.

So this file guards the parse half, before the lift that item 4 orders moves the
title read upstream. The distinction the tests encode: the ruled next step is a
DETERMINISTIC TEXT READ and adds no resource, so lifting it in keeps every
assertion here green. What these tests fail on is an EXTRACTION pass appearing
before the leaf exists -- a model call, a plugin dispatch, a baml client.
"""
import re
from pathlib import Path

import pytest

from doc_tools.components.document_parser import DocumentParserComponent

# The live ingress-user instance's kwargs, kept in step with
# `doc_tools/definitions.py`'s `user_document_parser`. Only the fields that bear
# on this invariant are set; `config` is irrelevant to resource keys.
USER_DROP_KWARGS = dict(
    name="process_user_document_artifact",
    partition_name="user_pdf_files",
    obtained_via="user-drop",
    path_prefix_strip="ingress-user/",
    sidecar_manifest_name="manifest.json",
    downstream_graph_asset="build_user_knowledge_graph",
)

PARSER_SOURCE = Path("doc_tools/components/document_parser.py")


def _user_drop_asset():
    defs = DocumentParserComponent(**USER_DROP_KWARGS).build_defs(None)
    return next(iter(defs.assets))


# --------------------------------------------------------------------------- #
# 1. The structural reason the invariant holds: no model resource to call.
# --------------------------------------------------------------------------- #
def test_the_user_drop_parse_asset_takes_only_s3():
    """`parse + text layer only` is not a convention here, it is the asset's
    signature. An extraction pass needs a model client; this asset is handed one
    resource and it is S3. Adding `llm` to the parse step is the exact change the
    ruling forbids before the leaf exists, and it fails here.
    """
    keys = set(_user_drop_asset().required_resource_keys)
    # `io_manager` is Dagster's own and is on every asset: it is what pickles the
    # parse artifact to the dropper's own prefix, which is the one write the ruling
    # DOES want here ("visible to the dropper only"). The claim under test is about
    # the resources the asset's own code reaches for.
    keys -= {"io_manager"}
    assert keys == {"s3"}, (
        f"the user-drop parse asset's resources changed to {sorted(keys)}. Item 4 "
        f"of the 2026-10-21 leaf ruling says a pdf runs parse + text layer only "
        f"before the title read. If this now takes a model resource, an extraction "
        f"pass can run before the leaf is known."
    )


@pytest.mark.parametrize("forbidden", ["llm", "weaviate", "neo4j", "jena"])
def test_the_parse_step_cannot_reach_a_model_or_a_store(forbidden):
    """Named one by one so a failure says WHICH arrived. `weaviate`/`neo4j`/`jena`
    are here for the second half of the ruled order -- nothing is written for a
    drop whose origin is unresolved, and a store resource on the parse step is how
    that would start happening by accident.
    """
    assert forbidden not in set(_user_drop_asset().required_resource_keys)


# --------------------------------------------------------------------------- #
# 2. The same invariant at the source level, because a resource is not the only
#    way to call a model: an import would do.
# --------------------------------------------------------------------------- #
def test_the_parse_module_dispatches_no_extraction_pass():
    """A `required_resource_keys` check cannot see a module-level baml client or a
    plugin import. This one can. It is deliberately a substring seal rather than
    an AST walk: the thing being guarded is coarse (no extraction here, at all),
    and a coarse guard that is obvious to read survives longer.

    Note what is NOT forbidden: `doc_tools.utils.sustainment_header_trust`, which
    is where the title read lives. It is deterministic text handling with no
    client, and item 4 orders it to run here next.
    """
    src = PARSER_SOURCE.read_text(encoding="utf-8")
    # Strip comments before scanning. The module's prose legitimately NAMES the
    # sustainment plugin while explaining an env var it shares, and a comment
    # cannot call anything.
    code = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    )
    code = re.sub(r'""".*?"""', "", code, flags=re.DOTALL)

    for forbidden in (
        "import baml",
        "from baml",
        "baml_client",
        "doc_tools.plugins",
        "from doc_tools import plugins",
        "get_plugin",
        "ExtractHeader",
        "ExtractParts",
        "ExtractWorkInstructions",
    ):
        assert forbidden not in code, (
            f"{PARSER_SOURCE} now references {forbidden!r} in code. The user-drop "
            f"parse step runs parse + text layer only until the leaf is known "
            f"(leaf ruling 2026-10-21, item 4); an extraction pass here runs "
            f"before anything knows what the document is."
        )


# --------------------------------------------------------------------------- #
# 3. The lift is compatible: the ruled next step needs no resource at all.
#
# This is the test that makes the file useful rather than merely restrictive. If
# the title read needed a model, item 4 would be impossible as written -- the
# read would have to come with the very resource the invariant above forbids.
# It does not, and this pins that.
# --------------------------------------------------------------------------- #
def test_the_title_read_needs_no_resource_so_the_lift_stays_inside_the_invariant():
    from doc_tools.utils import sustainment_header_trust as header_trust

    # The shape the parse already produces: typed elements with text.
    elements = [
        {"type": "NarrativeText", "text": "Vendor Semiconductor Inc."},
        {"type": "Title", "text": "PRODUCT CHANGE NOTICE"},
        {"type": "Title", "text": "PCN-24-210412"},
        {"type": "Title", "text": "Table 2 - EOL Devices with Life-time Buy"},
    ]

    leaf, source = header_trust.doc_type_from_titles(
        header_trust.headline_candidates(elements))

    # No client, no resource, no network, no model: the call above is the whole
    # dependency. The leaf is decided from the document's own printing.
    assert leaf == "PCN"
    assert source == "title", (
        "the read's source string feeds the ruling's leaf_source enum, whose "
        "member is 'title' -- see the report of 2026-10-21"
    )


def test_a_later_caption_cannot_overturn_the_headline():
    """Guards the property the lift must not lose. The fourth element above is a
    table caption carrying a PDN keyword ('EOL'); first-signal-wins means the
    headline decides. Measured on the real corpus: a blob scan refused both
    Diodes notices on exactly this caption.
    """
    from doc_tools.utils import sustainment_header_trust as header_trust

    headline_first = [
        {"type": "Title", "text": "PRODUCT CHANGE NOTICE"},
        {"type": "Title", "text": "Table 2 - EOL Devices with Life-time Buy"},
    ]
    assert header_trust.doc_type_from_titles(
        header_trust.headline_candidates(headline_first))[0] == "PCN"
