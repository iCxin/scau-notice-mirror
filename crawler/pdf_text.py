"""从 PDF 附件中抽取文本，让 PDF 型通知也能被搜索到。"""
from __future__ import annotations

import re
from io import BytesIO


def extract_pdf_text(data: bytes, max_pages: int = 20) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return ""
        pages = reader.pages[:max_pages]
        chunks = [page.extract_text() or "" for page in pages]
    except Exception:
        return ""

    text = "\n".join(chunks)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text if len(text) >= 20 else ""
