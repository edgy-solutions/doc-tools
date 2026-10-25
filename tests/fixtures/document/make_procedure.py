"""Regenerate the document-kind outline fixture (a 6-page procedure PDF).

Why it exists: the document outline pass must read numbered and unnumbered
headings, must NOT read admonition labels (``WARNING``, ``CAUTION:``) as
headings, and must ignore page furniture (``Page N of 6``). Every line below is
deliberate; a line that does not survive text extraction verbatim is useless
to that pass, so ``--verify`` asserts it.

There is no PDF writer in the venv, so this emits raw PDF syntax (base-14
Helvetica, xref table). Output is deterministic: no timestamps, a constant /ID,
fixed object order. Re-running yields IDENTICAL bytes; the committed
``procedure_fixture.pdf`` is canonical, so any change to its sha256 is a
contract change: re-pin wherever the sha is pinned. Write is bytes with ``\\n``
newlines (never ``write_text``). Run through the repo venv only:

    .venv/Scripts/python tests/fixtures/document/make_procedure.py [--check|--verify]
"""
import hashlib
import io
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "procedure_fixture.pdf"

PAGES = [
    ["TORQUE PROCEDURE TP-204",
     "Acme Manufacturing - Controlled Document",
     # A LABELLED title block, because identity.document_identity reads
     # "Label: value" and nothing else. Without the colons it refuses all four
     # fields and the row's identity arm contributes nothing to the golden --
     # which is what this fixture did until it was measured.
     "Document Number: TP-204",
     "Revision: B",
     "CAGE Code: 1ABC3"],
    ["1 PURPOSE",
     "This procedure defines the bolt torque sequence for the",
     "main flange assembly."],
    ["2 SAFETY PRECAUTIONS",
     "WARNING",
     "The line must be depressurised before any fastener is loosened.",
     "2.1 Lockout and tagout",
     "Isolate the supply valve and apply a personal lock."],
    ["2.2 Residual pressure check",
     "Open the bleed port and confirm zero reading on the gauge.",
     "CAUTION:",
     "Fluid may be hot."],
    ["3 TORQUE SEQUENCE",
     "Tighten the fasteners in a star pattern in three stages.",
     "3.1 Stage one - 30 Nm",
     "Apply 30 Nm to each fastener in the sequence shown."],
    ["3.2 Stage two - 60 Nm",
     "Apply 60 Nm in the same order.",
     "APPENDIX A",
     "Calibration records are retained for seven years."],
]


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _content(lines: list[str], n: int) -> bytes:
    ops = ["BT", "/F1 12 Tf", "14 TL", "72 720 Td"]
    for i, ln in enumerate(lines):
        ops.append(f"({_esc(ln)}) Tj" if i == 0 else f"T* ({_esc(ln)}) Tj")
    ops.append("ET")
    # Footer, far below the body so it is the last line top-to-bottom.
    ops += ["BT", "/F1 9 Tf", "280 40 Td", f"(Page {n} of {len(PAGES)}) Tj", "ET"]
    return ("\n".join(ops) + "\n").encode("latin-1")


def build() -> bytes:
    n = len(PAGES)
    # Objects: 1 catalog, 2 pages, 3 font, then per page (page, content).
    objs: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: ("<< /Type /Pages /Count %d /Kids [%s] >>" % (
            n, " ".join(f"{4 + 2 * i} 0 R" for i in range(n)))).encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, lines in enumerate(PAGES):
        pn, cn = 4 + 2 * i, 5 + 2 * i
        objs[pn] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {cn} 0 R >>").encode()
        body = _content(lines, i + 1)
        objs[cn] = (b"<< /Length %d >>\nstream\n" % len(body)) + body + b"endstream"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = out.tell()
        out.write(b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n")
    xref = out.tell()
    size = max(objs) + 1
    out.write(b"xref\n0 %d\n" % size)
    out.write(b"0000000000 65535 f \n")
    for num in range(1, size):
        out.write(b"%010d 00000 n \n" % offsets[num])
    out.write(b"trailer\n<< /Size %d /Root 1 0 R /ID [<00112233445566778899aabbccddeeff> "
              b"<00112233445566778899aabbccddeeff>] >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref))
    return out.getvalue()


def verify(data: bytes) -> int:
    import pdfplumber
    bad = 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        assert len(pdf.pages) == len(PAGES), f"{len(pdf.pages)} pages extracted"
        for i, (page, want) in enumerate(zip(pdf.pages, PAGES), 1):
            got = (page.extract_text() or "").split("\n")
            print(f"page {i}: {len(got)} extracted lines")
            for ln in want + [f"Page {i} of {len(PAGES)}"]:
                if ln not in got:
                    bad += 1
                    print(f"  MISSING verbatim: {ln!r}")
            if got[-1] != f"Page {i} of {len(PAGES)}":
                bad += 1
                print(f"  footer is not last line: {got[-1]!r}")
    assert build() == data, "generator is not deterministic"
    print("verify:", "OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


def main() -> int:
    data = build()
    sha = hashlib.sha256(data).hexdigest()
    if "--check" in sys.argv:
        ok = OUT.exists() and OUT.read_bytes() == data
        print(("match" if ok else "DIFFERS from disk"), "sha256:", sha)
        return 0 if ok else 1
    if "--verify" in sys.argv:
        print("sha256:", sha)
        return verify(data)
    with io.open(OUT, "wb") as f:
        f.write(data)
    print(f"wrote {OUT} ({len(data)} bytes) sha256: {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
