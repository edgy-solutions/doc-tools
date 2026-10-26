"""render.pages: pdftoppm name mapping, soffice command line, error paths, parser wiring."""
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from doc_tools.passes import render
from doc_tools.passes.render import RenderError

DECK = Path(__file__).parent / "fixtures" / "training" / "hydraulics_fixture.pptx"


def _stub_pdf(monkeypatch, names):
    """Skip soffice; make the rasteriser write tiny PNGs under the given names."""
    monkeypatch.setattr(render, "_convert_to_pdf", lambda src, work_dir, t: "x.pdf")

    def _rast(pdf_path, work_dir, dpi, timeout_s):
        out = []
        for name in names:
            p = os.path.join(work_dir, name)
            Image.new("RGB", (8, 4), "white").save(p)
            out.append(p)
        return out

    monkeypatch.setattr(render, "_rasterize", _rast)


def test_name_mapping_unpadded(monkeypatch, tmp_path):
    _stub_pdf(monkeypatch, [f"p-{n}.png" for n in range(1, 10)])
    out = render.pages("d.pptx", str(tmp_path / "o"))
    assert [p["basename"] for p in out] == [f"page_{n}.png" for n in range(1, 10)]
    assert all(os.path.exists(p["path"]) for p in out)
    assert (out[0]["width"], out[0]["height"], out[0]["dpi"]) == (8, 4, 150)


def test_name_mapping_zero_padded(monkeypatch, tmp_path):
    _stub_pdf(monkeypatch, [f"p-{n:03d}.png" for n in range(1, 151)])
    out = render.pages("d.pptx", str(tmp_path / "o"))
    assert [p["page"] for p in out] == list(range(1, 151))
    assert out[-1]["basename"] == "page_150.png"


def test_gap_raises(monkeypatch, tmp_path):
    _stub_pdf(monkeypatch, [f"p-{n}.png" for n in (1, 2, 4, 5)])
    with pytest.raises(RenderError):
        render.pages("d.pptx", str(tmp_path / "o"))


def test_work_dir_is_cleaned(monkeypatch, tmp_path):
    _stub_pdf(monkeypatch, ["p-1.png"])
    out_dir = tmp_path / "o"
    render.pages("d.pptx", str(out_dir))
    assert sorted(os.listdir(out_dir)) == ["page_1.png"]


def _capture_run(monkeypatch, returncode=0, stderr=""):
    calls = []
    monkeypatch.setattr(render, "_soffice", lambda: "soffice")

    def _run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(subprocess, "run", _run)
    return calls


def test_pptx_command_line(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    with pytest.raises(RenderError):  # no PDF is produced by the fake run
        render._convert_to_pdf(str(tmp_path / "d.pptx"), str(tmp_path), 5)
    cmd = calls[0]
    assert any(a.startswith("-env:UserInstallation=file:") for a in cmd)
    assert "ExportHiddenSlides" in cmd[cmd.index("--convert-to") + 1]


def test_docx_uses_plain_pdf(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    with pytest.raises(RenderError):
        render._convert_to_pdf(str(tmp_path / "d.docx"), str(tmp_path), 5)
    cmd = calls[0]
    assert cmd[cmd.index("--convert-to") + 1] == "pdf"


def test_pdf_input_never_calls_soffice(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise AssertionError("soffice must not be called for a pdf")

    monkeypatch.setattr(render, "_convert_to_pdf", _boom)
    monkeypatch.setattr(render, "_soffice", _boom)
    monkeypatch.setattr(render, "_rasterize",
                        lambda pdf, wd, dpi, t: (Image.new("RGB", (4, 2)).save(os.path.join(wd, "p-1.png"))
                                                 or [os.path.join(wd, "p-1.png")]))
    out = render.pages("d.pdf", str(tmp_path / "o"))
    assert [p["page"] for p in out] == [1]


def test_nonzero_return_code_raises_with_stderr(monkeypatch, tmp_path):
    _capture_run(monkeypatch, returncode=77, stderr="kaboom-from-soffice")
    with pytest.raises(RenderError) as ei:
        render._convert_to_pdf(str(tmp_path / "d.pptx"), str(tmp_path), 5)
    assert "kaboom-from-soffice" in str(ei.value) and "77" in str(ei.value)


def test_pass_resolves_to_exactly_render():
    from doc_tools.passes.dispatch import resolve_python_pass

    hits = resolve_python_pass("render.pages")
    assert hits is not None and [m for m, _ in hits] == ["doc_tools.passes.render"]


def test_parser_records_render_error(monkeypatch):
    from tests.test_document_parser_versioning import _FakeS3Client
    from tests.test_training_workbench_golden import _parse_drop

    def _fail(*a, **k):
        raise RenderError("soffice exploded")

    monkeypatch.setattr(render, "pages", _fail)
    manifest = _parse_drop(_FakeS3Client(), monkeypatch)
    assert manifest["pages"] == []
    assert "soffice exploded" in manifest["pages_error"]


@pytest.mark.skipif(not (shutil.which("soffice") and shutil.which("pdftoppm")),
                    reason="needs LibreOffice and Poppler; sandbox image has both")
def test_real_render(tmp_path):
    out = render.pages(str(DECK), str(tmp_path / "o"))
    assert [p["basename"] for p in out] == [f"page_{n}.png" for n in range(1, 5)]
    assert all(p["width"] > p["height"] for p in out)
