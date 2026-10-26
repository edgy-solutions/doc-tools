"""``render.pages`` -- one PNG per page/slide of a deck or document.

Contract: ``docs/contracts/training-workbench.md`` section 5 (every slide gets
``pages/page_<n>.png``, ``n`` = the deck's 1-based slide number) and section 9
(the step-e surface, LibreOffice + Poppler).

Port of the workbench's ``src/ingestion/rendering.py`` with two deliberate
differences: no ``print`` (logging), and no swallow-and-return-``[]`` -- a failed
render raises :class:`RenderError`, because an empty list is indistinguishable
from "a deck with no pages".
"""
from __future__ import annotations

import glob
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_PRESENTATIONS = (".pptx", ".ppt", ".odp")
_DOCUMENTS = (".docx", ".doc")

# Measured in the sandbox image (LibreOffice 25.2.3) on fixture
# long-with-hidden-slides: plain "pdf" exports 147 pages for 150 slides, because
# the default drops hidden slides and shifts every later page number. With
# ExportHiddenSlides it exports 150, so page_{n} stays slide n.
_IMPRESS_TARGET = 'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'
_PLAIN_TARGET = "pdf"

_PDFTOPPM_NAME = re.compile(r"^p-(\d+)\.png$")


class RenderError(RuntimeError):
    """The page render failed; nothing was produced."""


def _soffice() -> str:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    if platform.system() == "Linux":
        for bin_dir in ("/usr/bin", "/usr/local/bin", "/opt/libreoffice/program"):
            if os.path.isdir(bin_dir):
                matches = glob.glob(os.path.join(bin_dir, "libreoffice*")) + glob.glob(
                    os.path.join(bin_dir, "soffice*"))
                matches = sorted(m for m in matches if os.path.isfile(m) and os.access(m, os.X_OK))
                if matches:
                    return matches[0]
    if platform.system() == "Windows":
        for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                  r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
            if os.path.exists(p):
                return p
    raise RenderError("LibreOffice binary (soffice/libreoffice) not found; cannot convert to PDF")


def _pdftoppm() -> str:
    found = shutil.which("pdftoppm")
    if not found:
        raise RenderError("Poppler binary pdftoppm not found; cannot rasterise PDF")
    return found


def _run(cmd: list[str], timeout_s: int, what: str) -> None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"{what} timed out after {timeout_s}s") from exc
    except OSError as exc:
        raise RenderError(f"{what} could not be started: {exc}") from exc
    if result.returncode != 0:
        tail = (result.stderr or "")[-500:]
        raise RenderError(f"{what} failed with return code {result.returncode}: {tail}")


def _convert_to_pdf(src: str, work_dir: str, timeout_s: int) -> str:
    ext = os.path.splitext(src)[1].lower()
    target = _IMPRESS_TARGET if ext in _PRESENTATIONS else _PLAIN_TARGET
    profile_dir = tempfile.mkdtemp(prefix="soffice_profile_", dir=work_dir)
    cmd = [_soffice(), f"-env:UserInstallation={Path(profile_dir).as_uri()}",
           "--headless", "--convert-to", target, "--outdir", work_dir, src]
    logger.info("render.pages: converting %s to PDF", os.path.basename(src))
    _run(cmd, timeout_s, "LibreOffice conversion")
    pdf_path = os.path.join(work_dir, f"{os.path.splitext(os.path.basename(src))[0]}.pdf")
    if not os.path.exists(pdf_path):
        raise RenderError(f"LibreOffice conversion produced no PDF at {pdf_path}")
    return pdf_path


def _rasterize(pdf_path: str, work_dir: str, dpi: int, timeout_s: int) -> list[str]:
    """Run pdftoppm; return the pdftoppm-named files (``p-1.png`` / ``p-001.png``)."""
    prefix = os.path.join(work_dir, "p")
    _run([_pdftoppm(), "-png", "-r", str(dpi), pdf_path, prefix], timeout_s, "pdftoppm")
    return sorted(os.path.join(work_dir, f) for f in os.listdir(work_dir)
                  if _PDFTOPPM_NAME.match(f))


def pages(file_path: str, out_dir: str, *, dpi: int | None = None,
          timeout_s: int | None = None) -> list[dict]:
    """Render every page/slide of a deck or document to out_dir/page_{n}.png (n 1-based).

    Returns [{"page": n, "path": <local path>, "basename": "page_{n}.png", "width",
    "height", "dpi"}], ordered by n. Raises RenderError on any failure (never
    returns [] on error).
    """
    if dpi is None:
        dpi = int(os.getenv("TRAINING_PAGE_RENDER_DPI", "150"))
    if timeout_s is None:
        timeout_s = int(os.getenv("TRAINING_PAGE_RENDER_TIMEOUT_S", "300"))
    ext = os.path.splitext(file_path)[1].lower()
    if ext != ".pdf" and ext not in _PRESENTATIONS + _DOCUMENTS:
        raise RenderError(f"cannot render {ext or 'extensionless'} input {os.path.basename(file_path)!r}")

    os.makedirs(out_dir, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="render_", dir=out_dir)
    try:
        pdf_path = file_path if ext == ".pdf" else _convert_to_pdf(file_path, work_dir, timeout_s)
        raster_dir = os.path.join(work_dir, "raster")
        os.makedirs(raster_dir)
        files = _rasterize(pdf_path, raster_dir, dpi, timeout_s)

        by_page: dict[int, str] = {}
        for f in files:
            m = _PDFTOPPM_NAME.match(os.path.basename(f))
            by_page[int(m.group(1))] = f
        n_pages = len(by_page)
        if n_pages == 0 or sorted(by_page) != list(range(1, n_pages + 1)):
            raise RenderError(
                f"rasterised pages are not exactly 1..N: got {sorted(by_page)}")

        out: list[dict] = []
        for n in range(1, n_pages + 1):
            dest = os.path.join(out_dir, f"page_{n}.png")
            shutil.move(by_page[n], dest)
            with Image.open(dest) as im:
                width, height = im.size
            out.append({"page": n, "path": dest, "basename": f"page_{n}.png",
                        "width": width, "height": height, "dpi": dpi})
        logger.info("render.pages: %d pages from %s", n_pages, os.path.basename(file_path))
        return out
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
