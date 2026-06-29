"""IADS-bundle ingest — unpack a `.iads` container into S3 so the
existing `xml_graph_sync_job` per-WP path can finish the work.

Closes the 40051 image-rendering gap surfaced in the 2026-06-29
corpus-ingest investigation: the helmet TM bundle's WP XMLs reference
graphics via ``<graphic boardno="MS098897A">`` and the 40051 parser
predicts an S3 PNG path for each figure, but the .iads bundle's actual
graphics (CGM) never make it into S3 because the existing XML-ingest
path takes one .xml file at a time and doesn't know about the
companion container.

This asset is the **bundle-level** entry point:

  1. Reads a `.iads` file from S3 (per `IadsIngestConfig.s3_key`).
  2. Iterates ALL entries (WP XMLs + graphics) via
     ``iter_iads_entries`` — the new sibling of the XML-only iterator.
  3. Uploads each WP XML to a predictable per-bundle path under
     ``40051/<project/program/.../>/<bundle_basename>/<wp_filename>.xml``.
     The path mirrors the bundle's location in ``iads/...`` so
     architects can organize by ``iads/army/aviation/helmet.iads``
     and get ``40051/army/aviation/helmet/M0004.xml`` as the
     corresponding per-WP file.
  4. Converts CGM graphics to PNG via Inkscape (see
     ``doc_tools/utils/cgm_convert``) and uploads to the path each
     WP's 40051 parser will predict — i.e., the per-WP
     ``generated/<wp_basename>/images/<graphic>.png`` dir. The same
     PNG is uploaded under EACH WP's predicted path so the parser's
     existing image-prefix logic keeps working without modification.
     (Storage cost is small for current bundles; we can dedupe to a
     bundle-shared dir later if it matters.)
  5. Other graphic formats (JPG, PNG, BMP, G4, GIF) are uploaded
     as-is — only CGM needs conversion. The 40051 parser writes the
     same `.png` extension in its predicted URL regardless of source
     format; we honor that by renaming the uploaded file's extension
     while keeping its bytes. For .G4 (fax) we leave as-is for now
     because the parser doesn't predict G4 URLs and the cortex-ui
     FederatedImage doesn't render G4 either.

Per the architect's 2026-06-29 ruling:

  > "add sensor too - bucket prefix is fine just make sure we can
  > support depths to the tree so that I can organize by project/program"

The path-derivation here uses ``os.path.dirname`` of the bundle's
S3 key so ANY depth under the ``iads/`` prefix is honored. A
bundle at ``iads/foo/bar/baz/helmet.iads`` unpacks to
``40051/foo/bar/baz/helmet/...``.

Triggering the downstream `xml_graph_sync_job` per WP is handled
by the new ``iads_unpacked_sensor`` — when this asset uploads a
WP XML, the sensor sees it and launches the existing job. This
keeps the bundle-extraction and per-WP-ingest decoupled.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
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

    Exactly one shape must be provided. See ``XmlIngestConfig.resolve``
    for the equivalent contract on the per-WP path.
    """

    s3_bucket: Optional[str] = None
    s3_key: Optional[str] = None
    file_url: Optional[str] = None

    def resolve(self) -> tuple[str, str]:
        if self.s3_bucket and self.s3_key:
            return self.s3_bucket, self.s3_key
        if self.file_url:
            parsed = urlparse(self.file_url)
            if parsed.scheme != "s3" or not parsed.netloc or not parsed.path:
                raise ValueError(
                    f"file_url must be an s3:// URI with bucket+key; "
                    f"got {self.file_url!r}"
                )
            return parsed.netloc, parsed.path.lstrip("/")
        raise ValueError(
            "IadsIngestConfig requires either (s3_bucket+s3_key) or file_url."
        )


# Mapping from raw graphic extensions to the on-disk extension we upload.
# CGM gets converted to PNG. Other raster formats keep their original
# extension. The 40051 parser writes `.png` URLs unconditionally, so the
# CGM->PNG rename handles the boom diagram path; other formats remain
# accessible via direct S3 path even if the parser doesn't reference them.
_UPLOAD_EXT_MAP = {
    ".cgm": ".png",
    ".jpg": ".jpg",
    ".jpeg": ".jpg",
    ".png": ".png",
    ".bmp": ".bmp",
    ".gif": ".gif",
    ".pcx": ".pcx",
    # .G4 (TIFF Group 4 fax) stays — see module docstring.
    ".g4": ".g4",
    # .pic is a small IADS preview thumbnail; skip — not user-facing.
}

# Graphic extensions we ever upload at all. Files outside this set
# (.ent, .dtd, .dcf, .fos, .scc, .ico, etc.) are skipped — they're
# IADS-tool metadata, not user-facing content.
_GRAPHIC_EXTS = set(_UPLOAD_EXT_MAP.keys())


@asset(partitions_def=iads_files_partition)
def extract_iads_bundle(
    context: AssetExecutionContext,
    config: IadsIngestConfig,
    s3: S3Resource,
) -> MaterializeResult:
    """Download a .iads from S3, unpack, convert CGM->PNG, upload all.

    Partitioned by `iads_files_partition` (DynamicPartitionsDefinition);
    the `iads_sensor` registers a new partition per bundle key it
    discovers under the `iads/` prefix. The partition key is the
    bundle's S3 key with `/` replaced by `__` (the S3SensorComponent
    convention — see dag_tools/components/s3_sensor for the rationale).
    """

    s3_client = s3.get_client()

    s3_bucket, s3_key = config.resolve()

    # 1. Fetch the bundle bytes (zero local-disk dependency for the
    #    .iads file itself; we still need a temp file for CGM conversion
    #    because Inkscape reads from disk).
    context.log.info(
        f"Fetching IADS bundle from s3://{s3_bucket}/{s3_key}"
    )
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

    context.log.info(
        f"IADS bundle: {len(iads_bytes)} bytes; parsing manifest…"
    )

    # 2. Derive the bundle's S3 layout from its key.
    #    `iads/army/aviation/helmet.iads` →
    #      bundle_basename = "helmet"
    #      target_dir      = "40051/army/aviation/helmet"
    #      per_wp_image_dir(wpname) = target_dir + f"/generated/{wpname}/images"
    src_dir = os.path.dirname(s3_key)  # "iads/army/aviation"
    bundle_basename = os.path.splitext(os.path.basename(s3_key))[0]  # "helmet"
    # Replace the leading "iads/" prefix with "40051/" so the per-WP
    # ingest sensor (which watches XML files under standard doc-type
    # prefixes) picks up the unpacked content. ANY depth between
    # `iads/` and the bundle is preserved per the architect's
    # 2026-06-29 directive "support depths to the tree so that I can
    # organize by project/program".
    if src_dir.startswith("iads/"):
        unpacked_dir = src_dir.replace("iads/", "40051/", 1) + "/" + bundle_basename
    elif src_dir == "iads":
        unpacked_dir = "40051/" + bundle_basename
    else:
        # Defensive: caller put the bundle outside `iads/`; mirror the
        # exact path under `40051/<bundle_basename>/`. Architect chose
        # the iads/ convention but we don't reject other locations.
        unpacked_dir = (
            f"{src_dir}/{bundle_basename}" if src_dir else bundle_basename
        )
    context.log.info(
        f"Bundle target dir: s3://{s3_bucket}/{unpacked_dir}/ "
        f"(bundle_basename={bundle_basename!r})"
    )

    # 3. Write the .iads to a tempfile so we can mmap/seek (the
    #    iter_iads_entries helper reads the whole file via Path.read_bytes
    #    anyway, but a tempfile lets us reuse the existing API
    #    unchanged).
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_p = Path(tmpdir)
        iads_local = tmpdir_p / "bundle.iads"
        iads_local.write_bytes(iads_bytes)

        # ────────────────────────────────────────────────────────────
        # First pass: collect WP XMLs (basename-only, no path) and
        # graphics. We need the WP list before uploading graphics so
        # we can replicate each graphic under each WP's predicted
        # image_prefix dir.
        # ────────────────────────────────────────────────────────────
        wp_xmls: List[tuple[str, bytes]] = []  # (basename_with_ext, body)
        graphics: List[tuple[str, bytes]] = []  # (basename_with_ext, body)

        for relpath, body in iter_iads_entries(iads_local):
            basename = relpath.replace("\\", "/").rsplit("/", 1)[-1]
            ext = os.path.splitext(basename)[1].lower()
            if ext == ".xml":
                wp_xmls.append((basename, body))
            elif ext in _GRAPHIC_EXTS:
                graphics.append((basename, body))
            # All other entries (.ent, .dtd, .dcf, .fos, .scc, .ico,
            # .pic, .db, etc.) are deliberately skipped — they're
            # IADS-tool internals, not corpus content.

        context.log.info(
            f"IADS inventory: {len(wp_xmls)} WP XMLs, "
            f"{len(graphics)} graphics for upload"
        )

        # ────────────────────────────────────────────────────────────
        # Convert CGM graphics once into the tempdir. Convert each
        # graphic at most once, even though we upload it per-WP.
        # ────────────────────────────────────────────────────────────
        prepared_graphics: List[tuple[str, bytes, str]] = []
        # tuple = (uploaded_filename_with_target_ext, uploaded_bytes, content_type)
        inkscape_ok = inkscape_available()
        if not inkscape_ok:
            context.log.warning(
                "inkscape not available on PATH — CGM graphics will be "
                "skipped this run. Add `inkscape` to the doc-tools "
                "Dockerfile or install locally to enable CGM conversion."
            )

        cgm_converted = 0
        cgm_failed = 0
        for basename, body in graphics:
            ext = os.path.splitext(basename)[1].lower()
            target_ext = _UPLOAD_EXT_MAP[ext]
            target_filename = os.path.splitext(basename)[0] + target_ext

            if ext == ".cgm":
                if not inkscape_ok:
                    cgm_failed += 1
                    continue
                src_file = tmpdir_p / basename
                out_file = tmpdir_p / target_filename
                src_file.write_bytes(body)
                try:
                    convert_cgm_to_png(src_file, out_file)
                    out_bytes = out_file.read_bytes()
                    cgm_converted += 1
                except CgmConvertError as e:
                    cgm_failed += 1
                    context.log.warning(
                        f"CGM convert failed for {basename}: {e} "
                        f"(skipped — bundle continues)"
                    )
                    continue
            else:
                out_bytes = body

            # Crude content-type map. The S3 GetObject side only needs
            # this for the federated_image proxy to set the right
            # Content-Type header back to the browser.
            content_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".bmp": "image/bmp",
                ".gif": "image/gif",
                ".pcx": "image/x-pcx",
                ".g4": "image/g4-fax",
            }.get(target_ext, "application/octet-stream")

            prepared_graphics.append((target_filename, out_bytes, content_type))

        context.log.info(
            f"Graphics prepared: {len(prepared_graphics)} ready for upload "
            f"(CGM: {cgm_converted} converted, {cgm_failed} failed/skipped)"
        )

        # ────────────────────────────────────────────────────────────
        # Upload WP XMLs first so the downstream `iads_unpacked_sensor`
        # has the canonical inputs available BEFORE the graphics it
        # might cross-reference. (Order is defensive — both must be
        # present before the per-WP ingest runs, but the sensor is
        # cursor-based and will pick up whichever fires its threshold
        # first.)
        # ────────────────────────────────────────────────────────────
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

        # ────────────────────────────────────────────────────────────
        # Replicate prepared graphics under EACH WP's predicted
        # image_prefix path. The 40051 parser's
        # `image_prefix = s3://{bucket}/{base_dir}/generated/{base_name}/images/`
        # where base_dir = dirname(s3_key) and base_name =
        # filename.replace('.','_'). With our upload above, each WP
        # gets its own predicted prefix; we mirror the same set of
        # graphics under each. Small storage hit; keeps the parser
        # unchanged (architecturally clean — the parser doesn't need
        # to know about bundles).
        # ────────────────────────────────────────────────────────────
        graphic_upload_count = 0
        for wp_basename, _ in wp_xmls:
            wp_base_name_dot = wp_basename.replace(".", "_")
            wp_image_dir = f"{unpacked_dir}/generated/{wp_base_name_dot}/images"
            for target_filename, out_bytes, content_type in prepared_graphics:
                graphic_key = f"{wp_image_dir}/{target_filename}"
                s3_client.put_object(
                    Bucket=s3_bucket,
                    Key=graphic_key,
                    Body=out_bytes,
                    ContentType=content_type,
                )
                graphic_upload_count += 1

        context.log.info(
            f"IADS unpack complete: {len(wp_xml_keys)} WP XMLs, "
            f"{graphic_upload_count} graphic uploads "
            f"({len(prepared_graphics)} unique × {len(wp_xmls)} WPs)"
        )

    return MaterializeResult(
        metadata={
            "source_bundle": MetadataValue.text(
                f"s3://{s3_bucket}/{s3_key}"
            ),
            "unpacked_dir": MetadataValue.text(
                f"s3://{s3_bucket}/{unpacked_dir}/"
            ),
            "wp_xml_count": MetadataValue.int(len(wp_xml_keys)),
            "wp_xml_keys": MetadataValue.json(wp_xml_keys),
            "graphics_unique_count": MetadataValue.int(len(prepared_graphics)),
            "graphics_total_uploaded": MetadataValue.int(graphic_upload_count),
            "cgm_converted": MetadataValue.int(cgm_converted),
            "cgm_failed_or_skipped": MetadataValue.int(cgm_failed),
            "inkscape_available": MetadataValue.bool(inkscape_ok),
        }
    )
