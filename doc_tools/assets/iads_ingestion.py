"""IADS-bundle ingest — unpack a `.iads` container into S3 so the
existing `xml_graph_sync_job` per-WP path can finish the work.

Closes the 40051 image-rendering gap surfaced 2026-06-29 (the helmet TM
bundle's `<graphic boardno="MS098897A">` references the boom diagram
inside helmet.iads but the existing per-XML ingest path didn't unpack
the companion container).

## Rendering-origin discipline (2026-06-29 ruling)

The architect's explicit framing: **Path 3 (honest-failure placeholder)
is the system behavior, not the consolation prize. Path 1 (labeled
override) is layered on top — never disguised as pipeline output.**

This asset enforces that by emitting a per-figure ``.meta.json``
sidecar next to every uploaded graphic. The sidecar's
``rendering_origin`` field tells the cortex-ui slide-in panel WHICH
of three states this figure is in:

  - ``"pipeline"`` — the IADS extractor converted the source format
    successfully (no override present). The PNG at the predicted
    path IS the pipeline's output.
  - ``"supplied_override"`` — an operator placed a hand-converted
    PNG at the bundle's `.overrides/` path; the UI MUST label this
    visibly so "we hand-supplied this" never reads as "the pipeline
    rendered this." A future engineer must be able to tell
    instantly which figures were hand-fed and which weren't.
  - ``"format_not_supported"`` — the conversion failed AND no
    override exists. The PNG at the predicted path either does
    not exist or is intentionally absent; the UI renders a
    placeholder card with the figure ID, title, source format,
    and a click-through to the raw source bytes (preserved at
    `source_graphics/<name>.cgm`).

`[[honest-failure-as-demo-asset]]` applied to the format layer:
the system reports what it actually did. The next CGM that hits
the pipeline without an override produces an honest placeholder,
not a blank space the operator has to debug.

## Override convention

Operators supply a hand-converted PNG by placing it at
``<bundle_dir>/<bundle_basename>.overrides/<figure_basename>.png``.
For the helmet bundle this is
``iads/army/aviation/helmet.overrides/MS098897A.png``.

The override:
1. Wins over pipeline conversion when both exist.
2. Is uploaded to the SAME predicted path as a pipeline rendering
   (so the 40051 parser's URL prediction stays correct).
3. Has its origin recorded in the `.meta.json` sidecar so the UI
   shows the "supplied rendering" label.

## Bundle layout produced by this asset

For ``iads/army/aviation/helmet.iads``:

```
40051/army/aviation/helmet/
├── M0004.xml                                   # WP XMLs unpacked
├── T0003.xml
├── ...
├── generated/M0004_xml/images/                 # parser-predicted
│   ├── MS098897A.png                           # if rendered/overridden
│   ├── MS098897A.meta.json                     # always present
│   ├── helmet.jpg
│   ├── helmet.meta.json
│   └── ...
├── generated/T0003_xml/images/                 # replicated per WP
│   └── ... (same set)
└── source_graphics/                            # preserved raw bytes
    ├── ms098897a.cgm                           # for click-through
    ├── helmet.jpg
    └── ...
```

The per-WP replication keeps the parser's predicted URL stable.
The bundle-shared ``source_graphics/`` preserves originals once for
the click-through-to-source link the UI offers when rendering fails.

NOTE on `from __future__ import annotations`: deliberately NOT used
in this module. PEP 563 stringifies all annotations, and Dagster's
``infer_schema_from_config_annotation`` (used by the @asset
decorator for partitioned assets) can't resolve string-form types
on Config classes — it raises ``DagsterInvalidPythonicConfigDefinition
Error: Unable to resolve config type 'IadsIngestConfig'``. Smoke-
tested at tests/test_dagster_config_load.py.
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from dagster import asset, AssetExecutionContext, Config, MaterializeResult, MetadataValue
from dagster_aws.s3 import S3Resource

from doc_tools.parsers.iads_extract import iter_iads_entries
from doc_tools.partitions import iads_files_partition
from doc_tools.utils.cgm_convert import (
    CgmConvertError,
    convert_cgm_to_png,
    inkscape_available,
)


class IadsIngestConfig(Config):
    """Two-shape config matching `XmlIngestConfig`'s contract:

    1. ``{s3_bucket, s3_key}`` — manual-launchpad shape.
    2. ``{file_url: "s3://bucket/key"}`` — S3SensorComponent shape used
       by the new ``iads_sensor`` (added 2026-06-29).

    Exactly one shape must be provided. Use ``resolve_iads_config()``
    (module-level free function below) to normalize to (bucket, key).

    Empty-string-as-unset is the form Dagster's Pythonic-config schema
    inference accepts for partitioned assets. ``Optional[str] = None``
    LOOKS equivalent but trips ``DagsterInvalidPythonicConfigDefinition
    Error: Unable to resolve config type``. The existing
    ``IngestionConfig`` (doc_tools/config.py) uses the same shape and
    works; matching that pattern.
    """

    s3_bucket: str = ""
    s3_key: str = ""
    file_url: str = ""


def resolve_iads_config(config: IadsIngestConfig) -> tuple[str, str]:
    """Normalize the two-shape IadsIngestConfig to (bucket, key).

    Treats empty string as "field unset" (see Config docstring for
    why we don't use Optional)."""
    if config.s3_bucket and config.s3_key:
        return config.s3_bucket, config.s3_key
    if config.file_url:
        parsed = urlparse(config.file_url)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
            raise ValueError(
                f"file_url must be an s3:// URI with bucket+key; "
                f"got {config.file_url!r}"
            )
        return parsed.netloc, parsed.path.lstrip("/")
    raise ValueError(
        "IadsIngestConfig requires either (s3_bucket+s3_key) or file_url."
    )


# Mapping from raw graphic extensions to the on-disk extension we upload.
# CGM gets converted to PNG (when conversion succeeds OR an override exists).
# Other raster formats keep their original extension. The 40051 parser
# writes `.png` URLs unconditionally, so the CGM->PNG rename handles the
# boom diagram path; other formats remain accessible via direct S3 path
# even if the parser doesn't reference them.
_UPLOAD_EXT_MAP = {
    ".cgm": ".png",
    ".jpg": ".jpg",
    ".jpeg": ".jpg",
    ".png": ".png",
    ".bmp": ".bmp",
    ".gif": ".gif",
    ".pcx": ".pcx",
    ".g4": ".g4",
    # .pic skipped — IADS preview thumbnails, not user-facing.
}

# Graphic extensions we ever upload at all. Files outside this set
# (.ent, .dtd, .dcf, .fos, .scc, .ico, .pic, etc.) are skipped — they're
# IADS-tool internals, not corpus content.
_GRAPHIC_EXTS = set(_UPLOAD_EXT_MAP.keys())

_CONTENT_TYPE_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".pcx": "image/x-pcx",
    ".g4": "image/g4-fax",
}


# Rendering-origin enum. These string values are the contract with the
# cortex-ui slide-in panel; renaming them is a breaking change.
RENDERING_ORIGIN_PIPELINE = "pipeline"
RENDERING_ORIGIN_OVERRIDE = "supplied_override"
RENDERING_ORIGIN_UNSUPPORTED = "format_not_supported"


@asset(partitions_def=iads_files_partition)
def extract_iads_bundle(
    context: AssetExecutionContext,
    config: IadsIngestConfig,
    s3: S3Resource,
) -> MaterializeResult:
    """Download a .iads from S3, unpack WPs + graphics, emit .meta.json
    sidecars per figure.

    Partitioned by `iads_files_partition`; the `iads_sensor` registers
    a new partition per bundle key it discovers under the `iads/`
    prefix. See module docstring for the rendering-origin discipline
    and bundle layout.
    """
    s3_client = s3.get_client()
    s3_bucket, s3_key = resolve_iads_config(config)

    # 1. Fetch the bundle bytes (we need a tempfile for CGM conversion
    #    later — LibreOffice reads from disk — but the IADS bytes
    #    themselves stay in memory).
    context.log.info(f"Fetching IADS bundle from s3://{s3_bucket}/{s3_key}")
    response = None
    try:
        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        iads_bytes = response["Body"].read()
    finally:
        if response is not None:
            try:
                response["Body"].close()
            except Exception:
                pass

    context.log.info(f"IADS bundle: {len(iads_bytes)} bytes; parsing manifest…")

    # 2. Derive bundle S3 layout. ANY depth between `iads/` and the
    #    bundle is preserved per the 2026-06-29 "support depths" ruling.
    src_dir = os.path.dirname(s3_key)
    bundle_basename = os.path.splitext(os.path.basename(s3_key))[0]
    if src_dir.startswith("iads/"):
        unpacked_dir = src_dir.replace("iads/", "40051/", 1) + "/" + bundle_basename
    elif src_dir == "iads":
        unpacked_dir = "40051/" + bundle_basename
    else:
        unpacked_dir = f"{src_dir}/{bundle_basename}" if src_dir else bundle_basename

    # Override directory convention: sibling to the bundle, named
    # `<bundle>.overrides/`. Architects organize this by hand; the
    # asset just checks for matching basenames at extract time.
    overrides_dir = (
        f"{src_dir}/{bundle_basename}.overrides" if src_dir
        else f"{bundle_basename}.overrides"
    )

    # Source-graphics dir: bundle-level (NOT per-WP) so we preserve
    # each unique original exactly once. The UI's click-through-to-
    # source link points here when rendering fails or for the
    # "view raw source" affordance.
    source_graphics_dir = f"{unpacked_dir}/source_graphics"

    context.log.info(
        f"Bundle target dir: s3://{s3_bucket}/{unpacked_dir}/ | "
        f"overrides dir: s3://{s3_bucket}/{overrides_dir}/ | "
        f"source_graphics dir: s3://{s3_bucket}/{source_graphics_dir}/"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_p = Path(tmpdir)
        iads_local = tmpdir_p / "bundle.iads"
        iads_local.write_bytes(iads_bytes)

        # 3. First pass: split entries into WP XMLs vs graphics.
        wp_xmls: List[Tuple[str, bytes]] = []
        graphics: List[Tuple[str, bytes]] = []

        for relpath, body in iter_iads_entries(iads_local):
            basename = relpath.replace("\\", "/").rsplit("/", 1)[-1]
            ext = os.path.splitext(basename)[1].lower()
            if ext == ".xml":
                wp_xmls.append((basename, body))
            elif ext in _GRAPHIC_EXTS:
                graphics.append((basename, body))
            # Everything else: IADS-tool metadata, skip.

        context.log.info(
            f"IADS inventory: {len(wp_xmls)} WP XMLs, "
            f"{len(graphics)} graphic entries"
        )

        # 4. Prepare each graphic: classify rendering_origin, prepare
        #    bytes for upload (or None for unsupported), preserve
        #    source bytes, build the meta sidecar payload.
        converter_ok = inkscape_available()
        if not converter_ok:
            context.log.warning(
                "No CGM converter on PATH — CGM graphics with no override "
                "will be labeled `format_not_supported`. Install libreoffice "
                "(preferred) or inkscape in the doc-tools Dockerfile."
            )

        # PreparedGraphic: per-figure dict carrying everything we
        # need to upload across all WPs + write the source + meta.
        prepared: List[Dict[str, Any]] = []

        counts = {"pipeline": 0, "supplied_override": 0, "format_not_supported": 0}

        for basename, body in graphics:
            ext = os.path.splitext(basename)[1].lower()
            figure_basename = os.path.splitext(basename)[0]
            target_ext = _UPLOAD_EXT_MAP[ext]
            target_filename = figure_basename + target_ext

            # Source preservation: every original goes to
            # source_graphics/, regardless of rendering outcome. The
            # source IS the truth even when the pipeline can't render
            # it. UI's "view raw source" link points here.
            source_s3_uri = f"s3://{s3_bucket}/{source_graphics_dir}/{basename}"

            # Override check: case-insensitive on basename so the
            # ENTITY-declaration case mismatch (XML refs MS098897A.cgm,
            # IADS-internal file is ms098897a.cgm) is handled. Operators
            # who place an override should match whichever case the
            # figure_basename produces; that's the XML-side basename
            # since that's what the parser's predicted URL uses.
            override_bytes, override_key = _try_fetch_override(
                s3_client, s3_bucket, overrides_dir, figure_basename, target_ext,
                context=context,
            )

            # Decide rendering_origin + the bytes to upload.
            uploaded_bytes: Optional[bytes] = None
            origin: str
            convert_error: Optional[str] = None

            if override_bytes is not None:
                # Override wins, always — even if pipeline conversion
                # would have succeeded. Operator deliberately supplied
                # something; the system honors that AND labels it.
                uploaded_bytes = override_bytes
                origin = RENDERING_ORIGIN_OVERRIDE
                context.log.info(
                    f"figure {figure_basename}: using supplied override at "
                    f"s3://{s3_bucket}/{override_key} (rendering_origin="
                    f"{origin})"
                )
            elif ext == ".cgm":
                # CGM with no override → try converter.
                if not converter_ok:
                    origin = RENDERING_ORIGIN_UNSUPPORTED
                else:
                    src_file = tmpdir_p / basename
                    out_file = tmpdir_p / target_filename
                    src_file.write_bytes(body)
                    try:
                        convert_cgm_to_png(src_file, out_file)
                        uploaded_bytes = out_file.read_bytes()
                        origin = RENDERING_ORIGIN_PIPELINE
                    except CgmConvertError as e:
                        convert_error = str(e)[:300]
                        origin = RENDERING_ORIGIN_UNSUPPORTED
                        context.log.info(
                            f"figure {figure_basename}: CGM conversion "
                            f"failed ({convert_error}); rendering_origin="
                            f"{origin} (no override present)"
                        )
            else:
                # Non-CGM raster → passthrough.
                uploaded_bytes = body
                origin = RENDERING_ORIGIN_PIPELINE

            counts[origin] += 1

            content_type = _CONTENT_TYPE_BY_EXT.get(
                target_ext, "application/octet-stream"
            )
            source_content_type = _CONTENT_TYPE_BY_EXT.get(
                ext, "application/octet-stream"
            )

            # Meta sidecar payload. This is the contract with the
            # cortex-ui slide-in. ADDING fields is safe; renaming or
            # removing is a breaking UI change. JSON is keyed by the
            # uploaded filename (without .meta.json suffix) so the
            # UI can fetch with a predictable URL: replace the
            # `.png`/`.jpg`/... extension with `.meta.json`.
            meta: Dict[str, Any] = {
                "schema_version": 1,
                "figure_id": figure_basename,
                "rendering_origin": origin,
                "source_format": ext.lstrip("."),
                "source_s3": source_s3_uri,
                "uploaded_filename": target_filename,
                "supplied_override_s3": (
                    f"s3://{s3_bucket}/{override_key}" if override_key else None
                ),
                "convert_error": convert_error,  # populated only on UNSUPPORTED
            }

            prepared.append({
                "figure_basename": figure_basename,
                "uploaded_filename": target_filename,
                "uploaded_bytes": uploaded_bytes,  # None for UNSUPPORTED
                "content_type": content_type,
                "source_basename": basename,
                "source_bytes": body,
                "source_content_type": source_content_type,
                "meta": meta,
                "meta_filename": figure_basename + ".meta.json",
            })

        context.log.info(
            f"Graphics classified: pipeline={counts['pipeline']}, "
            f"supplied_override={counts['supplied_override']}, "
            f"format_not_supported={counts['format_not_supported']}"
        )

        # 5. Upload WP XMLs.
        wp_xml_keys: List[str] = []
        for basename, body in wp_xmls:
            target_key = f"{unpacked_dir}/{basename}"
            s3_client.put_object(
                Bucket=s3_bucket,
                Key=target_key,
                Body=body,
                ContentType="application/xml",
            )
            wp_xml_keys.append(target_key)
            context.log.info(f"uploaded WP XML: s3://{s3_bucket}/{target_key}")

        # 6. Upload source graphics once (bundle-level), regardless
        #    of rendering outcome. UI's view-raw-source link reads here.
        for p in prepared:
            source_key = f"{source_graphics_dir}/{p['source_basename']}"
            s3_client.put_object(
                Bucket=s3_bucket,
                Key=source_key,
                Body=p["source_bytes"],
                ContentType=p["source_content_type"],
            )

        # 7. Replicate prepared graphics (bytes + meta sidecar) under
        #    EACH WP's predicted image_prefix dir. The 40051 parser's
        #    `image_prefix = s3://{bucket}/{base_dir}/generated/{base_name}/images/`
        #    where base_name = filename.replace('.','_'). We mirror the
        #    same set of (PNG, meta.json) pairs under each WP so the
        #    parser-predicted URL works without parser changes.
        upload_count = {"figures": 0, "metas": 0, "skipped_unsupported": 0}
        for wp_basename, _ in wp_xmls:
            wp_base_name_dot = wp_basename.replace(".", "_")
            wp_image_dir = f"{unpacked_dir}/generated/{wp_base_name_dot}/images"

            for p in prepared:
                meta_key = f"{wp_image_dir}/{p['meta_filename']}"
                # Always write the meta sidecar — even for UNSUPPORTED.
                # The UI uses presence-of-meta as the discovery signal;
                # absence-of-meta means "no info about this figure."
                s3_client.put_object(
                    Bucket=s3_bucket,
                    Key=meta_key,
                    Body=json.dumps(p["meta"], indent=2).encode("utf-8"),
                    ContentType="application/json",
                )
                upload_count["metas"] += 1

                if p["uploaded_bytes"] is None:
                    # UNSUPPORTED: meta sidecar already records the
                    # truth; we deliberately DO NOT upload a PNG. UI
                    # checks meta first, then renders the placeholder
                    # card. (If we uploaded a 0-byte or broken PNG
                    # here, FederatedImage would have rendering
                    # artifacts before the UI got a chance to read
                    # meta. Better: no PNG at all when rendering_origin
                    # is `format_not_supported`.)
                    upload_count["skipped_unsupported"] += 1
                    continue

                graphic_key = f"{wp_image_dir}/{p['uploaded_filename']}"
                s3_client.put_object(
                    Bucket=s3_bucket,
                    Key=graphic_key,
                    Body=p["uploaded_bytes"],
                    ContentType=p["content_type"],
                )
                upload_count["figures"] += 1

        # 8. Per-bundle graphics manifest — the SINGLE source of truth the
        #    parser reads to construct correct `mil:hasURL` triples.
        #    Previously the parser hardcoded `<boardno>.png` for every
        #    figure regardless of the source format the extractor uploaded
        #    (CGM, JPG, BMP, PNG, GIF, PCX, G4) — a prediction that masked
        #    a structural information-loss bug. Now the parser fetches this
        #    manifest from a predictable sibling path (next to the WP XML)
        #    and reads each figure's actual uploaded filename + rendering
        #    origin, eliminating the prediction surface.
        #
        #    Indexed by figure_basename (matches the XML's
        #    `<graphic boardno="..."/>` attribute). Both the parser AND the
        #    cortex-ui slide-in (next session) consume this contract; see
        #    `[[verification-must-fail]]` — predictions silently degrade
        #    when the assumption breaks, manifests fail loud (missing key
        #    is recognizable).
        manifest_key = f"{unpacked_dir}/graphics_manifest.json"
        manifest_doc = {
            "schema_version": 1,
            "bundle_source": f"s3://{s3_bucket}/{s3_key}",
            "unpacked_dir": f"s3://{s3_bucket}/{unpacked_dir}/",
            "figures": {
                p["figure_basename"]: {
                    "uploaded_filename": p["uploaded_filename"],
                    "source_format": p["meta"]["source_format"],
                    "rendering_origin": p["meta"]["rendering_origin"],
                    "source_s3": p["meta"]["source_s3"],
                    "supplied_override_s3": p["meta"]["supplied_override_s3"],
                    "convert_error": p["meta"]["convert_error"],
                }
                for p in prepared
            },
        }
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=manifest_key,
            Body=json.dumps(manifest_doc, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        context.log.info(
            f"Wrote graphics manifest with {len(manifest_doc['figures'])} "
            f"figures: s3://{s3_bucket}/{manifest_key}"
        )

        context.log.info(
            f"IADS unpack complete: {len(wp_xml_keys)} WP XMLs, "
            f"{upload_count['figures']} figure PNGs, "
            f"{upload_count['metas']} meta sidecars, "
            f"{upload_count['skipped_unsupported']} UNSUPPORTED "
            f"(no PNG, meta records why)"
        )

    return MaterializeResult(
        metadata={
            "source_bundle": MetadataValue.text(f"s3://{s3_bucket}/{s3_key}"),
            "unpacked_dir": MetadataValue.text(f"s3://{s3_bucket}/{unpacked_dir}/"),
            "overrides_dir": MetadataValue.text(f"s3://{s3_bucket}/{overrides_dir}/"),
            "source_graphics_dir": MetadataValue.text(
                f"s3://{s3_bucket}/{source_graphics_dir}/"
            ),
            "wp_xml_count": MetadataValue.int(len(wp_xml_keys)),
            "wp_xml_keys": MetadataValue.json(wp_xml_keys),
            "graphics_unique_count": MetadataValue.int(len(prepared)),
            "rendering_origin_pipeline": MetadataValue.int(counts["pipeline"]),
            "rendering_origin_supplied_override": MetadataValue.int(
                counts["supplied_override"]
            ),
            "rendering_origin_format_not_supported": MetadataValue.int(
                counts["format_not_supported"]
            ),
            "converter_available": MetadataValue.bool(converter_ok),
            "figure_pngs_uploaded": MetadataValue.int(upload_count["figures"]),
            "meta_sidecars_uploaded": MetadataValue.int(upload_count["metas"]),
        }
    )


def _try_fetch_override(
    s3_client,
    bucket: str,
    overrides_dir: str,
    figure_basename: str,
    target_ext: str,
    *,
    context: AssetExecutionContext,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Look for ``<overrides_dir>/<figure_basename>.<target_ext>``.

    Per the architect's 2026-06-29 ruling, the override is *labeled* —
    its presence is recorded in the meta sidecar's ``rendering_origin``
    so the UI never reads "we hand-supplied this" as "the pipeline
    rendered this." This helper just fetches the bytes; the asset
    sets the label.

    Returns ``(bytes, key)`` on hit, ``(None, None)`` on miss. Any
    error other than NoSuchKey is logged + treated as miss (defensive:
    don't kill the whole ingest because the operator's override is
    momentarily unreachable).
    """
    candidates = [target_ext, ".png", ".jpg", ".svg"]
    seen: set[str] = set()
    for ext in candidates:
        if ext in seen:
            continue
        seen.add(ext)
        key = f"{overrides_dir}/{figure_basename}{ext}"
        try:
            obj = s3_client.get_object(Bucket=bucket, Key=key)
            body = obj["Body"].read()
            try:
                obj["Body"].close()
            except Exception:
                pass
            return body, key
        except s3_client.exceptions.NoSuchKey:
            continue
        except Exception as e:
            context.log.warning(
                f"override probe at s3://{bucket}/{key} failed "
                f"(treated as miss): {e}"
            )
            continue
    return None, None
