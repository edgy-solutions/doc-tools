"""IADS container extractor — the tool-specific layer of the 40051 track.

Per the architect's 2026-06-13 40051-track assignment:

  > "iads_extract (unpack the .iads container — tool-specific) →
  >  read_40051_wp (parse WP XML — format-general) →
  >  classify_40051 (root-tag → mil: kind — format-general).
  >  Keep iads_extract isolated so the EAGLE adapter later swaps only
  >  the first."

This module is the ONLY place that knows about the IADS container
binary format. The downstream layers (mil_40051_ingest,
mil_40051_classifier) operate on raw WP XML bytes and don't care
whether they came from an .iads archive, an EAGLE export, or a loose
directory of XML files.

The IADS file format (observed from helmet.iads — IADS 4.0):

  [outer XML manifest <Package>...</Package>]
  [concatenated gzip blobs, one per package entry]

The manifest enumerates each entry with:
  <PackageFile>
    <RelativeFilepath>path\\inside\\package.xml</RelativeFilepath>
    <LastWriteTime>...</LastWriteTime>
    <CompressedLength>NNNN</CompressedLength>
  </PackageFile>

The blobs are gzip streams placed end-to-end after the manifest. Each
entry's CompressedLength reports the framed length, which can include
a small framing prefix before the gzip magic bytes (1F 8B 08). We
locate the gzip magic within the declared slice and decompress from
there, advancing the offset by the entry's declared CompressedLength
regardless.

The extractor is a generator that yields (relative_path, xml_bytes)
tuples for every entry whose path ends in .xml — the format-general
reader can decide whether it's a WP or non-WP front-matter.

Boundary discipline: this module reads bytes from disk and yields
in-memory. It does NOT write to a substrate. The caller (or a
pipeline orchestrator) decides what to do with each yielded WP.
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Iterator, Optional


# Manifest is a small subset of XML at the head of every .iads file.
# We parse it with a regex rather than lxml because the manifest is
# guaranteed to be ASCII and we want to be able to walk the file
# without loading the whole multi-MB binary blob.
_PACKAGE_FILE_RE = re.compile(
    r"<PackageFile>\s*"
    r"<RelativeFilepath>([^<]*)</RelativeFilepath>"
    r"\s*<LastWriteTime>[^<]*</LastWriteTime>"
    r"\s*<CompressedLength>(\d+)</CompressedLength>",
    re.MULTILINE,
)

_GZIP_MAGIC = b"\x1f\x8b\x08"


def _read_manifest(data: bytes) -> tuple[int, list[tuple[str, int]]]:
    """Parse the leading XML manifest from .iads bytes.

    Returns (manifest_end_offset, [(relpath, compressed_length), ...]).
    Raises if the manifest's closing tag isn't found (corrupt file).
    """
    closing = b"</Package>"
    end = data.find(closing)
    if end < 0:
        raise ValueError(
            "IADS manifest <Package> closing tag not found. The file is "
            "either not an IADS archive or is corrupt."
        )
    manifest_end = end + len(closing)
    manifest_str = data[:manifest_end].decode("utf-8", errors="ignore")
    entries: list[tuple[str, int]] = [
        (m.group(1), int(m.group(2)))
        for m in _PACKAGE_FILE_RE.finditer(manifest_str)
    ]
    return manifest_end, entries


def _decompress_at(data: bytes, slice_start: int, slice_len: int) -> Optional[bytes]:
    """Find the gzip magic within data[slice_start:slice_start+slice_len]
    and stream-decompress from there.

    Returns the decompressed bytes, or None if no gzip magic is found
    within the slice (anomalous entry, skip).
    """
    end = slice_start + slice_len
    search_end = min(len(data), end + 64)  # allow tiny trailing slop
    gz_start = data.find(_GZIP_MAGIC, slice_start, search_end)
    if gz_start < 0:
        return None
    # 16 + 15 → gzip with auto-detect window. Streaming decompress
    # because slice_len's framing can be off-by-a-few-bytes.
    try:
        return zlib.decompressobj(16 + 15).decompress(data[gz_start:])
    except zlib.error:
        return None


def iter_iads_xml_entries(iads_path: Path | str) -> Iterator[tuple[str, bytes]]:
    """Yield (relative_path, decompressed_bytes) for every .xml entry.

    Iterates the .iads file's entries in declaration order. Only yields
    entries whose RelativeFilepath ends in .xml — non-XML resources
    (graphics, ent files, etc.) are skipped at this layer (the
    format-general reader is XML-only).

    The relative_path is returned VERBATIM as the manifest declared it
    (Windows-style backslashes intact). Callers that want a basename
    for fixture matching should derive it.
    """
    for relpath, body in iter_iads_entries(iads_path):
        if relpath.lower().endswith(".xml"):
            yield relpath, body


def iter_iads_entries(iads_path: Path | str) -> Iterator[tuple[str, bytes]]:
    """Yield (relative_path, decompressed_bytes) for EVERY entry in the .iads.

    Sibling of :func:`iter_iads_xml_entries` for callers that need access
    to non-XML resources too — most importantly the graphics (CGM, JPG,
    G4, PNG, BMP) that the WP XMLs reference via ``<graphic boardno=...>``.
    The 40051 parser produces ``mil:Figure`` URIs with predicted S3 paths
    derived from those board numbers; this iterator surfaces the actual
    bytes so an upstream Dagster asset can convert (e.g., CGM->PNG via
    Inkscape) and upload to those predicted paths.

    The same per-entry framing logic as the XML iterator applies — each
    entry's CompressedLength is the framed length and gzip magic is
    located within the slice. Entries that fail to decompress (no gzip
    magic in the declared slice) are skipped silently and the manifest
    offset advances per declaration.

    Returned ``relative_path`` is the manifest's VERBATIM value
    (Windows backslashes intact). Callers should derive basenames for
    case-insensitive matching against the XML entity references — the
    helmet.iads sample emits ``Graphics\\ms098897a.cgm`` even though
    M0004.xml's ENTITY declaration says ``..\\graphics\\MS098897A.cgm``.
    """
    iads_path = Path(iads_path)
    data = iads_path.read_bytes()
    manifest_end, entries = _read_manifest(data)

    offset = manifest_end
    for relpath, clen in entries:
        body = _decompress_at(data, offset, clen)
        if body is not None:
            yield relpath, body
        offset += clen


def iter_iads_wp_xml_entries(iads_path: Path | str) -> Iterator[tuple[str, bytes]]:
    """Yield (relative_path, decompressed_bytes) for every WP XML entry.

    Same as iter_iads_xml_entries but filters out non-WP front-matter
    (TOC, frntcover, titleblk, etc.) by peeking at the root element.

    Convenience wrapper for the common ingest case where the caller
    only wants the WPs. The classifier's NON_WP_ROOT_TAGS set is the
    shared opinion on what's front-matter.
    """
    # Import here to avoid a circular: ingest imports classifier, classifier
    # imports nothing from this module, but iads_extract is at the
    # tool-specific tip and imports the format-general layer to filter.
    from doc_tools.parsers.mil_40051_classifier import NON_WP_ROOT_TAGS

    _root_tag_re = re.compile(rb"<([A-Za-z][\w.\-]*)[\s>/]")
    for relpath, body in iter_iads_xml_entries(iads_path):
        # find the first non-doctype-non-pi element
        root_tag: Optional[str] = None
        for m in _root_tag_re.finditer(body):
            tag = m.group(1).decode("ascii", errors="ignore")
            if tag.lower() == "xml" or tag.startswith("!") or tag.startswith("?"):
                continue
            root_tag = tag
            break
        if root_tag is None or root_tag in NON_WP_ROOT_TAGS:
            continue
        yield relpath, body


def iads_manifest_summary(iads_path: Path | str) -> dict:
    """Return a small diagnostic dict for the .iads at iads_path.

    Useful for predictions/probes that want to know how many entries,
    how many .xml entries, etc., without decompressing anything.
    """
    iads_path = Path(iads_path)
    data = iads_path.read_bytes()
    _, entries = _read_manifest(data)
    xml = [(p, c) for p, c in entries if p.lower().endswith(".xml")]
    return {
        "path": str(iads_path),
        "total_entries": len(entries),
        "xml_entries": len(xml),
        "non_xml_entries": len(entries) - len(xml),
        "first_xml_paths": [p for p, _ in xml[:5]],
    }
