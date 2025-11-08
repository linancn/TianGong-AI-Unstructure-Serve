import pytest

from src.utils import file_conversion


def test_format_extension_list_normalizes_and_sorts():
    result = file_conversion.format_extension_list([".Doc", "pptx", "md", None, ""])
    assert result == ".doc, .md, .pptx"


def test_maybe_convert_office_to_pdf_skips_non_office():
    original = "/tmp/sample.txt"
    path, cleanup = file_conversion.maybe_convert_office_to_pdf(original, ".txt")
    assert path == original
    assert cleanup == []


def test_maybe_convert_office_to_pdf_calls_converter(monkeypatch):
    def fake_convert(path):
        assert path == "/tmp/sample.docx"
        return "/tmp/sample.pdf", ["/tmp/sample.pdf"]

    monkeypatch.setattr(
        file_conversion,
        "convert_office_document_to_pdf",
        fake_convert,
    )

    path, cleanup = file_conversion.maybe_convert_office_to_pdf("/tmp/sample.docx", ".docx")
    assert path.endswith(".pdf")
    assert cleanup == [path]


def test_maybe_convert_to_pdf_delegates_for_office(monkeypatch):
    def fake_convert(path):
        return "/tmp/converted.pdf", ["/tmp/converted.pdf"]

    monkeypatch.setattr(file_conversion, "convert_office_document_to_pdf", fake_convert)
    path, cleanup = file_conversion.maybe_convert_to_pdf("/tmp/sample.pptx", ".pptx")
    assert path == "/tmp/converted.pdf"
    assert cleanup == ["/tmp/converted.pdf"]


def test_convert_office_document_to_pdf_fails_without_libreoffice(monkeypatch):
    monkeypatch.setattr(file_conversion, "_find_libreoffice_executable", lambda: None)

    with pytest.raises(RuntimeError) as excinfo:
        file_conversion.convert_office_document_to_pdf("/tmp/missing.docx")

    assert "LibreOffice executable not found" in str(excinfo.value)
