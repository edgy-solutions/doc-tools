"""CGM → PNG conversion via Inkscape subprocess.

The military-doc ingest path (40051 / S1000D / IADS) gets graphics
references via ``<graphic boardno="...">`` and the 40051 parser
predicts an S3 PNG path under each WP's ``generated/.../images/``
directory. For the actual image bytes to land at that predicted path,
the IADS extractor needs to convert each CGM (the IADS native vector
format) into a browser-renderable raster.

We use **Inkscape** directly rather than ImageMagick wrapping it,
because:

  1. ImageMagick's CGM support is implemented as a delegate that
     shells out to Inkscape anyway — calling Inkscape directly skips
     one layer of indirection and one process spawn.
  2. ImageMagick's apt-get install in our base image historically
     pulls libopenjp2 transitive dependencies that 404 on Ubuntu
     security pool flux (observed 2026-06-29).
  3. Inkscape's CGM importer handles WebCGM 2.0 profile (the format
     the helmet.iads sample uses) reliably.

The Dockerfile installs ``inkscape`` via apt — see
``.github/workflows/build-container.yml`` (Dockerfile injection step).
Local dev that wants to exercise this path needs Inkscape too;
WSL Ubuntu-22.04 install is ``sudo apt install -y inkscape``.

Boundary discipline: this module shells out via subprocess and writes
to a caller-provided output path. Callers are responsible for cleanup
of the input file if it was extracted to a temp location. We do NOT
upload to S3 here — that's the asset's job.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class CgmConvertError(RuntimeError):
    """Raised when Inkscape fails to convert a CGM file.

    Includes the Inkscape stderr in the message so operators can
    diagnose without re-running. Per
    `[[trailing-steps-nonfatal]]`: callers in the ingest pipeline
    catch this and log-and-continue so one bad graphic doesn't kill
    a whole bundle, but the named exception keeps the failure mode
    distinguishable from other ingest errors.
    """


def inkscape_available() -> bool:
    """Return True if the inkscape executable resolves on PATH.

    Used by the ingest asset's pre-flight check so it can log a single
    "skipping CGM conversion (no inkscape)" message rather than failing
    every CGM in the bundle individually. The Docker image ships with
    Inkscape; this returns False only in dev environments that haven't
    installed it.
    """
    return shutil.which("inkscape") is not None


def convert_cgm_to_png(cgm_path: Path | str, png_path: Path | str) -> None:
    """Convert ``cgm_path`` to a PNG written at ``png_path``.

    Uses ``inkscape --export-type=png --export-filename=...`` which is
    Inkscape 1.x+ syntax (Inkscape 0.x used ``-z -e``; we deliberately
    pin to the 1.x form because the Docker image installs Ubuntu's
    current inkscape >=1.0).

    Args:
        cgm_path: Absolute or relative path to a .cgm file on disk.
        png_path: Where the rasterized PNG should be written. Parent
            directory must exist (the asset creates it during temp
            staging before this call).

    Raises:
        CgmConvertError: Inkscape returned non-zero, or wrote no output.
            The exception message includes Inkscape's stderr for
            diagnosis. Callers should catch + log + continue rather
            than aborting the whole ingest (the boom diagram failing
            shouldn't kill the rest of the helmet bundle).
    """
    cgm = Path(cgm_path)
    png = Path(png_path)
    if not cgm.exists():
        raise CgmConvertError(f"CGM input does not exist: {cgm}")
    png.parent.mkdir(parents=True, exist_ok=True)

    # Inkscape 1.x flag form. --export-type=png makes the output
    # format explicit (Inkscape otherwise infers from the filename
    # extension, but being explicit avoids surprise behavior on
    # case-mismatched extensions). --without-gui keeps it headless;
    # newer Inkscape (>=1.2) requires this implicitly so passing it
    # is harmless and forward-compatible.
    cmd = [
        "inkscape",
        str(cgm),
        "--export-type=png",
        f"--export-filename={png}",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # per-file ceiling; a single CGM should be sub-second
            check=False,
        )
    except FileNotFoundError as exc:
        raise CgmConvertError(
            "inkscape not found on PATH. Add `inkscape` to the doc-tools "
            "Dockerfile's apt install list, or install locally for dev."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CgmConvertError(
            f"inkscape conversion timed out after 120s for {cgm}"
        ) from exc

    if result.returncode != 0:
        raise CgmConvertError(
            f"inkscape exited {result.returncode} converting {cgm}: "
            f"{result.stderr.strip()[:500]}"
        )
    if not png.exists() or png.stat().st_size == 0:
        # Inkscape can silently produce a 0-byte file on some malformed
        # CGM inputs; treat that as failure.
        raise CgmConvertError(
            f"inkscape produced no output at {png} for {cgm} "
            f"(stderr: {result.stderr.strip()[:300]})"
        )
    logger.info(
        "cgm_convert: %s -> %s (%d bytes PNG)",
        cgm.name, png.name, png.stat().st_size,
    )
