import io

import pytest
from agreement_pdf import make_pdf, tiny_png
from nguit_tools.agreement_files import (
    FileProblem,
    inspect_file,
    pdf_text_pages,
    sniff,
)
from pypdf import PdfReader, PdfWriter

PDF = "application/pdf"
TEXT = "1. Lock-in. The Tenant is bound by a lock-in period of 11 months.\n2. Notice. 30 days."


def problem(data, declared):
    with pytest.raises(FileProblem) as caught:
        inspect_file(data, declared)
    return caught.value.code


def test_sniff_recognises_real_file_types_by_content():
    assert sniff(make_pdf(TEXT)) == PDF
    assert sniff(tiny_png()) == "image/png"
    assert sniff(b"\xff\xd8\xff\xe0" + b"0" * 20) == "image/jpeg"
    assert sniff(b"MZ\x90\x00 this is an exe") is None
    assert sniff(b"<html><script>alert(1)</script>") is None


def test_a_valid_pdf_is_accepted_with_its_page_count():
    assert inspect_file(make_pdf(TEXT), PDF) == (PDF, 1)
    assert inspect_file(make_pdf(TEXT, copies=20), PDF)[1] == 20


def test_a_photo_counts_as_one_page():
    assert inspect_file(tiny_png(), "image/png") == ("image/png", 1)


def test_more_than_twenty_pages_is_rejected():
    assert problem(make_pdf(TEXT, copies=21), PDF) == "too_many_pages"


@pytest.mark.parametrize(
    ("data", "declared", "code"),
    [
        (b"", PDF, "empty"),
        (b"just some text pretending to be a pdf", PDF, "wrong_type"),
        (b"MZ\x90\x00 an executable renamed to .pdf", PDF, "wrong_type"),
        (b"<svg onload=alert(1)></svg>", "image/png", "wrong_type"),
    ],
)
def test_other_file_types_are_rejected_even_if_the_name_says_pdf(data, declared, code):
    assert problem(data, declared) == code


def test_a_type_that_does_not_match_the_content_is_rejected():
    assert problem(tiny_png(), PDF) == "type_mismatch"
    assert problem(make_pdf(TEXT), "image/png") == "type_mismatch"


def test_oversize_files_are_rejected():
    assert problem(b"%PDF-" + b"0" * (16 * 1024 * 1024), PDF) == "too_large"


def test_a_password_protected_pdf_is_rejected_with_a_clear_message():
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(TEXT))))
    writer.encrypt("secret")
    out = io.BytesIO()
    writer.write(out)
    assert problem(out.getvalue(), PDF) == "password_protected"


def test_a_corrupt_pdf_is_rejected_not_crashed_on():
    assert problem(b"%PDF-1.4 garbage that is not a real pdf at all", PDF) == "unreadable_pdf"


def test_the_pdf_text_layer_is_read_page_by_page():
    pages = pdf_text_pages(make_pdf(TEXT, copies=3))
    assert [p.page for p in pages] == [1, 2, 3]
    assert "lock-in period of 11 months" in pages[0].text.replace("\n", " ")
