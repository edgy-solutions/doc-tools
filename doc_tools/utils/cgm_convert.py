"""CGM → PNG conversion for the IADS ingest path.

The military-doc ingest (40051 / S1000D / IADS) references graphics
via ``<graphic boardno="...">`` and the 40051 parser predicts an S3
PNG path under each WP's ``generated/.../images/`` directory. For the
predicted PNG to actually exist, the IADS extractor needs to convert
each CGM (IADS's native vector format) into a browser-renderable
raster.

**Converter: LibreOffice headless.** LibreOffice's Draw module imports
CGM and exports PNG; we already install ``libreoffice`` in the
doc-tools Docker image (for MS Office docs), so no new dependency.
Inkscape (also in the image now per the 2026-06-29 commit) does NOT
have native CGM import — it was the architect's initial preference
but verification showed Inkscape's import list omits CGM. LibreOffice
is the working path.

Invocation:
    libreoffice --headless --convert-to png --outdir <dir> <input.cgm>

LibreOffice writes ``<input>.png`` into ``--outdir``. We then move it
to the caller-specified output path.

Boundary discipline: this module shells out via subprocess and writes
to a caller-provided output path. Callers are responsible for cleanup
of the input file if it was extracted to a temp location. We do NOT
upload to S3 here — that's the asset's job.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class CgmConvertError(RuntimeError):
    """Raised when CGM->PNG conversion fails.

    Per ``[[trailing-steps-nonfatal]]``: callers in the ingest pipeline
    catch this and log-and-continue so one bad graphic doesn't kill a
    whole bundle. The named exception keeps the failure mode
    distinguishable from other ingest errors.
    """


def inkscape_available() -> bool:
    """Return True if a CGM converter is available on PATH.

    The function name is kept for API stability with callers committed
    before the Inkscape→LibreOffice pivot (2026-06-29). It now returns
    True when *any* of the supported converters resolves — LibreOffice
    (primary) or Inkscape (fallback for SVG-shaped CGMs only).
    """
    return shutil.which("libreoffice") is not None or shutil.which("inkscape") is not None


def convert_cgm_to_png(cgm_path: Path | str, png_path: Path | str) -> None:
    """Convert ``cgm_path`` to a PNG written at ``png_path``.

    Primary path: LibreOffice headless. Inkscape is tried as a
    last-resort fallback only if LibreOffice isn't installed — its
    CGM support is incidental at best and many WebCGM 2.0 files fail
    silently with a zero-byte PNG output.

    Args:
        cgm_path: Absolute or relative path to a .cgm file on disk.
        png_path: Where the rasterized PNG should be written. Parent
            directory must exist (the asset creates it during temp
            staging before this call).

    Raises:
        CgmConvertError: The converter returned non-zero or produced
            no/empty output. Callers should catch + log + continue
            rather than aborting the whole ingest.
    """
    cgm = Path(cgm_path)
    png = Path(png_path)
    if not cgm.exists():
        raise CgmConvertError(f"CGM input does not exist: {cgm}")
    png.parent.mkdir(parents=True, exist_ok=True)

    if shutil.which("libreoffice") is not None:
        _convert_with_libreoffice(cgm, png)
    elif shutil.which("inkscape") is not None:
        logger.warning(
            "libreoffice not on PATH; falling back to Inkscape for %s "
            "(known to fail silently on many WebCGM files)",
            cgm.name,
        )
        _convert_with_inkscape(cgm, png)
    else:
        raise CgmConvertError(
            "No CGM converter on PATH. Add `libreoffice` (preferred) or "
            "`inkscape` (best-effort fallback) to the doc-tools "
            "Dockerfile's apt install list."
        )

    if not png.exists() or png.stat().st_size == 0:
        # Converter "succeeded" but produced nothing usable — treat as
        # failure so the asset's per-CGM error counter increments and
        # the operator sees a real signal.
        raise CgmConvertError(
            f"converter produced no/empty output at {png} for {cgm}"
        )
    logger.info(
        "cgm_convert: %s -> %s (%d bytes PNG)",
        cgm.name, png.name, png.stat().st_size,
    )


def _convert_with_libreoffice(cgm: Path, png: Path) -> None:
    """LibreOffice headless CGM->PNG. Writes ``<input_basename>.png``
    into a tempdir then moves it to ``png``. We can't pass the output
    filename directly — LibreOffice only honors ``--outdir`` and uses
    the input's basename for the output filename."""
    with tempfile.TemporaryDirectory() as outdir:
        cmd = [
            "libreoffice",
            "--headless",
            "--convert-to", "png",
            "--outdir", outdir,
            str(cgm),
        ]
        try:
            # 300s timeout: LibreOffice's first-run can take ~10s to
            # initialize its user profile. Per-CGM conversion after
            # warmup is sub-second.
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CgmConvertError(
                f"libreoffice conversion timed out after 300s for {cgm}"
            ) from exc
        if result.returncode != 0:
            raise CgmConvertError(
                f"libreoffice exited {result.returncode} converting {cgm}: "
                f"{result.stderr.strip()[:500] or result.stdout.strip()[:500]}"
            )
        # LibreOffice names the output as <input_stem>.png in --outdir.
        produced = Path(outdir) / (cgm.stem + ".png")
        if not produced.exists():
            raise CgmConvertError(
                f"libreoffice claimed success but didn't write "
                f"{produced} (stderr: {result.stderr.strip()[:300]})"
            )
        shutil.move(str(produced), str(png))


def _convert_with_inkscape(cgm: Path, png: Path) -> None:
    """Best-effort Inkscape fallback. Inkscape's native import list
    does NOT include CGM; this path exists only because some users
    have inkscape installed without libreoffice. Expect frequent
    silent-zero-byte failures here — the wrapper guards them."""
    cmd = [
        "inkscape",
        str(cgm),
        "--export-type=png",
        f"--export-filename={png}",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CgmConvertError(
            f"inkscape conversion timed out after 120s for {cgm}"
        ) from exc
    if result.returncode != 0:
        raise CgmConvertError(
            f"inkscape exited {result.returncode} converting {cgm}: "
            f"{result.stderr.strip()[:500]}"
        )
