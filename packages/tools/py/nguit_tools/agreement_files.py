"""Checks an uploaded file really is what it says, and reads the text layer of PDFs.

Reading a PDF's own text layer does not involve any AI model, so it is an independent
source for checking that quoted clauses really exist.
"""

import io

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from nguit_tools.agreement_check import PageText

ALLOWED = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}
MAX_PAGES = 20
MAX_BYTES = 15 * 1024 * 1024
JPEG = b"\xff\xd8\xff"
PNG = b"\x89PNG\r\n\x1a\n"


class FileProblem(Exception):
    """The upload cannot be accepted. `message` is safe to show to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def sniff(data: bytes) -> str | None:
    """What the bytes actually are, whatever the filename or header claims."""
    if b"%PDF-" in data[:1024]:
        return "application/pdf"
    if data.startswith(JPEG):
        return "image/jpeg"
    if data.startswith(PNG):
        return "image/png"
    return None


def _reader(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise FileProblem(
                "password_protected",
                "This PDF is password protected. Remove the password and upload it again.",
            )
        return reader
    except FileProblem:
        raise
    except (PyPdfError, ValueError, OSError, KeyError, RecursionError) as exc:
        raise FileProblem(
            "unreadable_pdf", "We could not open this PDF. Try saving it again or upload a photo."
        ) from exc


def inspect_file(data: bytes, declared_type: str) -> tuple[str, int]:
    """Returns (real content type, page count) or raises FileProblem."""
    if not data:
        raise FileProblem("empty", "The file is empty.")
    if len(data) > MAX_BYTES:
        raise FileProblem("too_large", "The file is too large. The limit is 15 MB.")
    real = sniff(data)
    if real is None or real not in ALLOWED:
        raise FileProblem("wrong_type", "Only PDF, JPEG and PNG files are accepted.")
    if real != declared_type:
        raise FileProblem("type_mismatch", "The file does not match the type you selected.")
    if real != "application/pdf":
        return real, 1
    pages = len(_reader(data).pages)
    if pages == 0:
        raise FileProblem("unreadable_pdf", "This PDF has no pages.")
    if pages > MAX_PAGES:
        raise FileProblem(
            "too_many_pages", f"This PDF has {pages} pages. The limit is {MAX_PAGES}."
        )
    return real, pages


def pdf_text_pages(data: bytes) -> list[PageText]:
    """The text layer of each page. Empty for scanned PDFs, which have no text layer."""
    reader = _reader(data)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # one bad page must not lose the others
            text = ""
        pages.append(PageText(i, text.strip()))
    return pages
