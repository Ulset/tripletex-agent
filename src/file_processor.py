import base64
import logging

import fitz  # pymupdf
from openai import OpenAI

from src.models import FileAttachment

logger = logging.getLogger(__name__)

IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg"}


class FileProcessor:
    def process_files(
        self,
        files: list[FileAttachment],
        openai_api_key: str,
        openai_model: str,
    ) -> list[dict]:
        if not files:
            return []

        results = []
        for file in files:
            try:
                raw = base64.b64decode(file.content_base64)
            except Exception:
                logger.error("Failed to decode base64 for file %s", file.filename)
                results.append({"filename": file.filename, "extracted_text": ""})
                continue

            extracted = ""
            try:
                if file.mime_type == "application/pdf":
                    extracted = self._extract_pdf_text(raw, file, openai_api_key, openai_model)
                elif file.mime_type in IMAGE_MIME_TYPES:
                    extracted = self._extract_image_text(file.content_base64, file.mime_type, openai_api_key, openai_model)
                else:
                    logger.warning("Unsupported mime type %s for file %s", file.mime_type, file.filename)
            except Exception:
                logger.exception("Failed to process file %s", file.filename)

            results.append({"filename": file.filename, "extracted_text": extracted})

        return results

    def _extract_pdf_text(
        self,
        raw: bytes,
        file: FileAttachment,
        openai_api_key: str,
        openai_model: str,
    ) -> str:
        doc = fitz.open(stream=raw, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()

        text = "\n".join(text_parts).strip()
        if text:
            return text

        # Scanned PDF — render pages as images and use vision API
        logger.info("No extractable text in %s, falling back to vision API", file.filename)
        return self._extract_scanned_pdf_text(raw, openai_api_key, openai_model)

    def _extract_scanned_pdf_text(
        self,
        raw: bytes,
        openai_api_key: str,
        openai_model: str,
    ) -> str:
        doc = fitz.open(stream=raw, filetype="pdf")
        image_contents = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            img_b64 = base64.b64encode(img_bytes).decode()
            image_contents.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                }
            )
        doc.close()

        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=openai_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all text and data from this image"},
                        *image_contents,
                    ],
                }
            ],
        )
        return response.choices[0].message.content or ""

    def _extract_image_text(
        self,
        content_base64: str,
        mime_type: str,
        openai_api_key: str,
        openai_model: str,
    ) -> str:
        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=openai_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all text and data from this image"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{content_base64}"},
                        },
                    ],
                }
            ],
        )
        return response.choices[0].message.content or ""
