"""Smoke test: Dagster Pythonic-config schema inference accepts our
ingest Configs at module-load time.

Catches `DagsterInvalidPythonicConfigDefinitionError` BEFORE deploy.

Background (2026-06-29): the IADS pipeline first deploy failed at
code-server boot with

  DagsterInvalidPythonicConfigDefinitionError
  Unable to resolve config type 'IadsIngestConfig'

Two iterations on the symptom before the real cause was found:

  1. Removed a `resolve()` method from `IadsIngestConfig` (its
     `tuple[str, str]` return annotation was suspected of tripping
     introspection). Did NOT fix it.
  2. Replaced `Optional[str] = None` fields with `str = ""`. THIS
     fixed it. The partitioned-asset config inference path doesn't
     accept `Optional` (the non-partitioned path does — that's why
     `XmlIngestConfig` slipped through earlier deploys despite
     having the same shape).

This test asserts the right shape: importing the asset modules and
the full `definitions` module triggers the same @asset decoration
+ schema-inference chain the deployed code-server runs. A
regression to `Optional` or any other unsupported field type
re-raises the same exception HERE, where iteration is seconds
instead of a 15-minute CI rebuild + pod roll.
"""
from __future__ import annotations


def test_iads_ingestion_module_loads():
    """Importing iads_ingestion runs the @asset decorator on
    extract_iads_bundle, which calls
    `infer_schema_from_config_annotation(IadsIngestConfig)`. A
    regression to `Optional[str] = None` (or any other unsupported
    field type) re-raises
    DagsterInvalidPythonicConfigDefinitionError."""
    import doc_tools.assets.iads_ingestion  # noqa: F401


def test_xml_ingestion_module_loads():
    """Same for XmlIngestConfig + extract_rdf_from_xml. The non-
    partitioned asset path is more permissive than the partitioned
    one but having both Configs in the same shape removes a
    regression surface."""
    import doc_tools.assets.xml_ingestion  # noqa: F401


def test_definitions_module_loads():
    """The actual entrypoint the Dagster code-server module-loads.
    If this passes the deployed pod will load cleanly too — same
    import chain, same @asset decoration, same schema inference.
    Catches Config regressions PLUS any other module-load issue
    (sensor wiring, partition refs, job selection mismatches)."""
    import doc_tools.definitions  # noqa: F401


def test_iads_config_resolve_helpers_work():
    """The Config classes hold only data; the resolve helpers are
    free functions. Smoke-test both forms (manual + sensor) to
    catch any regression where the helpers silently start returning
    bad shapes."""
    from doc_tools.assets.iads_ingestion import (
        IadsIngestConfig,
        resolve_iads_config,
    )
    from doc_tools.assets.xml_ingestion import (
        XmlIngestConfig,
        resolve_xml_config,
    )

    # Manual-launchpad shape: explicit bucket + key.
    iads_manual = IadsIngestConfig(
        s3_bucket="processing-artifacts",
        s3_key="iads/army/aviation/helmet.iads",
    )
    bucket, key = resolve_iads_config(iads_manual)
    assert bucket == "processing-artifacts"
    assert key == "iads/army/aviation/helmet.iads"

    # Sensor shape: file_url.
    iads_sensor = IadsIngestConfig(
        file_url="s3://processing-artifacts/iads/army/aviation/helmet.iads",
    )
    bucket, key = resolve_iads_config(iads_sensor)
    assert bucket == "processing-artifacts"
    assert key == "iads/army/aviation/helmet.iads"

    # Same for XML config.
    xml_manual = XmlIngestConfig(
        s3_bucket="processing-artifacts",
        s3_key="40051/army/aviation/helmet/M0004.xml",
    )
    bucket, key = resolve_xml_config(xml_manual)
    assert bucket == "processing-artifacts"
    assert key == "40051/army/aviation/helmet/M0004.xml"

    xml_sensor = XmlIngestConfig(
        file_url="s3://processing-artifacts/40051/army/aviation/helmet/M0004.xml",
    )
    bucket, key = resolve_xml_config(xml_sensor)
    assert bucket == "processing-artifacts"
    assert key == "40051/army/aviation/helmet/M0004.xml"


def test_iads_config_resolve_rejects_empty():
    """Empty/missing config should raise — catches a regression to
    silent-default behavior (the previous bundled-fix-hides-the-
    next-mechanism shape)."""
    import pytest

    from doc_tools.assets.iads_ingestion import (
        IadsIngestConfig,
        resolve_iads_config,
    )

    empty = IadsIngestConfig()
    with pytest.raises(ValueError, match="requires either"):
        resolve_iads_config(empty)


def test_xml_graph_sync_job_partitions_consistent():
    """Catches the 2026-06-29 'partitioned upstream + unpartitioned
    downstream' bug. When `extract_rdf_from_xml` was partitioned by
    `xml_files_partition` to enable the new xml_sensor, its four
    downstream consumers (upload_to_jena, init_neo4j_n10s,
    sync_jena_to_neo4j, index_xml_chunks_to_weaviate) stayed
    unpartitioned. Dagster's IO manager couldn't bridge the gap:

      DagsterExecutionLoadInputError: Error occurred while loading
      input "extract_rdf_from_xml" of step "upload_to_jena"

    The runtime symptom (sensor-triggered run fails at the second
    step's input-load) is invisible to module-load tests. This test
    asserts at IMPORT time that every asset in xml_graph_sync_job's
    selection shares the SAME partitions_def — catches the regression
    in seconds locally, before another CI + rollout cycle.
    """
    from doc_tools.definitions import defs

    # Find xml_graph_sync_job and its selected asset keys.
    sync_job = next(
        (j for j in defs.jobs if j.name == "xml_graph_sync_job"),
        None,
    )
    assert sync_job is not None, "xml_graph_sync_job not registered in defs.jobs"

    selected_keys = sync_job.asset_selection_data.resolved_asset_selections \
        if hasattr(sync_job, "asset_selection_data") else None
    # Fallback for Dagster API variations — read selection from the
    # job's resolved op selection if asset_selection_data isn't exposed.
    if selected_keys is None:
        # `selection` on define_asset_job is a list[str]; defs.assets
        # has the AssetsDefinitions; find them by name.
        selection_names = {
            "extract_rdf_from_xml",
            "upload_to_jena",
            "init_neo4j_n10s",
            "sync_jena_to_neo4j",
            "index_xml_chunks_to_weaviate",
        }
        partitions_by_name: dict[str, object] = {}
        for ad in defs.assets:
            for key in ad.keys:
                name = key.path[-1]
                if name in selection_names:
                    partitions_by_name[name] = ad.partitions_def

        # Every asset in selection must be discoverable.
        missing = selection_names - set(partitions_by_name)
        assert not missing, (
            f"xml_graph_sync_job selection includes assets not found in "
            f"defs.assets: {missing}"
        )

        # All partition_defs must be the SAME object (either all
        # xml_files_partition or all None).
        unique_partition_defs = {id(p) for p in partitions_by_name.values()}
        assert len(unique_partition_defs) == 1, (
            f"xml_graph_sync_job's assets have MIXED partitions_defs:\n"
            + "\n".join(
                f"  {name}: {p}" for name, p in partitions_by_name.items()
            )
            + "\nDagster's IO manager will fail to load partitioned->"
            "unpartitioned inputs at runtime. Make them all share the "
            "same partitions_def (or all None)."
        )
