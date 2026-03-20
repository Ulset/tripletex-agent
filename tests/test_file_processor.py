import base64
from unittest.mock import MagicMock, patch

import fitz  # pymupdf

from src.file_processor import FileProcessor
from src.models import FileAttachment


def _make_test_pdf(text: str = "Hello World") -> bytes:
    """Create a minimal PDF with the given text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class TestFileProcessorEmptyFiles:
    def test_returns_empty_list_when_no_files(self):
        fp = FileProcessor()
        result = fp.process_files([], model="google/gemini-2.5-flash")
        assert result == []


class TestFileProcessorBase64Decoding:
    def test_decodes_base64_content(self):
        pdf_bytes = _make_test_pdf("Test content")
        b64 = base64.b64encode(pdf_bytes).decode()
        file = FileAttachment(filename="test.pdf", content_base64=b64, mime_type="application/pdf")

        fp = FileProcessor()
        result = fp.process_files([file], model="google/gemini-2.5-flash")

        assert len(result) == 1
        assert result[0]["filename"] == "test.pdf"
        assert "Test content" in result[0]["extracted_text"]


class TestFileProcessorPDF:
    def test_extracts_text_from_pdf(self):
        pdf_bytes = _make_test_pdf("Invoice #12345")
        b64 = base64.b64encode(pdf_bytes).decode()
        file = FileAttachment(filename="invoice.pdf", content_base64=b64, mime_type="application/pdf")

        fp = FileProcessor()
        result = fp.process_files([file], model="google/gemini-2.5-flash")

        assert len(result) == 1
        assert result[0]["filename"] == "invoice.pdf"
        assert "Invoice #12345" in result[0]["extracted_text"]

    @patch("src.file_processor.get_openai_client")
    def test_falls_back_to_vision_for_scanned_pdf(self, mock_openai_cls):
        # Create a PDF with no text (empty page)
        doc = fitz.open()
        doc.new_page()
        pdf_bytes = doc.tobytes()
        doc.close()

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Scanned text from vision"
        mock_client.chat.completions.create.return_value = mock_response

        b64 = base64.b64encode(pdf_bytes).decode()
        file = FileAttachment(filename="scanned.pdf", content_base64=b64, mime_type="application/pdf")

        fp = FileProcessor()
        result = fp.process_files([file], model="google/gemini-2.5-flash")

        assert result[0]["extracted_text"] == "Scanned text from vision"
        mock_openai_cls.assert_called_once()
        mock_client.chat.completions.create.assert_called_once()


class TestFileProcessorImage:
    @patch("src.file_processor.get_openai_client")
    def test_extracts_text_from_image(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Text from image"
        mock_client.chat.completions.create.return_value = mock_response

        img_b64 = base64.b64encode(b"fake-png-data").decode()
        file = FileAttachment(filename="receipt.png", content_base64=img_b64, mime_type="image/png")

        fp = FileProcessor()
        result = fp.process_files([file], model="google/gemini-2.5-flash")

        assert result[0]["filename"] == "receipt.png"
        assert result[0]["extracted_text"] == "Text from image"
        mock_openai_cls.assert_called_once()

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        content = messages[0]["content"]
        assert content[0]["text"] == "Extract all text and data from this image"
        assert "data:image/png;base64," in content[1]["image_url"]["url"]


class TestFileProcessorMultipleFiles:
    def test_processes_multiple_files(self):
        pdf1 = _make_test_pdf("First document")
        pdf2 = _make_test_pdf("Second document")

        files = [
            FileAttachment(filename="a.pdf", content_base64=base64.b64encode(pdf1).decode(), mime_type="application/pdf"),
            FileAttachment(filename="b.pdf", content_base64=base64.b64encode(pdf2).decode(), mime_type="application/pdf"),
        ]

        fp = FileProcessor()
        result = fp.process_files(files, model="google/gemini-2.5-flash")

        assert len(result) == 2
        assert "First document" in result[0]["extracted_text"]
        assert "Second document" in result[1]["extracted_text"]
