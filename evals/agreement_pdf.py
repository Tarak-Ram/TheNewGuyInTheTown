"""Makes real PDFs from the fake sample agreements, so uploads can be tried end to end.

    python evals/agreement_pdf.py     # writes evals/agreements/pdf/*.pdf

The text is wrapped by the PDF library, so text read back from it has hard line breaks,
like text from a real agreement.
"""

import io
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

HERE = Path(__file__).parent / "agreements"


def make_pdf(text: str, copies: int = 1) -> bytes:
    """A PDF with the text on one page, repeated `copies` times (one page each)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Fake sample agreement")
    style = getSampleStyleSheet()["BodyText"]
    story = []
    for n in range(copies):
        for line in text.splitlines():
            if line.strip():
                story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;"), style))
                story.append(Spacer(1, 6))
        if n < copies - 1:
            story.append(PageBreak())
    doc.build(story)
    return buffer.getvalue()


def main() -> None:
    out = HERE / "pdf"
    out.mkdir(exist_ok=True)
    for txt in sorted(HERE.glob("*.txt")):
        if txt.stem.startswith("i_"):
            continue  # needs a Devanagari font; use the .txt with the model path instead
        (out / f"{txt.stem}.pdf").write_bytes(make_pdf(txt.read_text(encoding="utf-8")))
        print("wrote", out / f"{txt.stem}.pdf")


if __name__ == "__main__":
    main()


def tiny_png() -> bytes:
    """A valid 1x1 PNG, for testing the photo upload path."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00\xff\xff\xff")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
