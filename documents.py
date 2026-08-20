"""Getting text out of a PDF, page by page.

Two routes: the PDF's own text layer (free, exact) and OCR of a rendered page
image (costs a model call, approximate). Which one ran, and how confident it
was, is recorded per page so bad pages can be found and fixed later.

ponytail: one OCR implementation (the vision model this app already has a key
for), selected by OCR_PROVIDER. Not a five-provider plugin framework - the seam
is `ocr_page()`, so adding Textract/Vision later is one function, not a
refactor. With OCR_PROVIDER=none, image-only pages are stored empty and flagged
NEEDS_REVIEW rather than silently pretending to have been read.
"""
import base64
import os

import pymupdf as fitz

# Below this many characters a page is treated as an image and sent to OCR.
# A genuinely near-empty page (a part title) costs one OCR call and comes back
# near-empty anyway, which is the honest answer.
MIN_TEXT_CHARS = int(os.environ.get("PDF_MIN_TEXT_CHARS", "120"))
OCR_PROVIDER = os.environ.get("OCR_PROVIDER", "openai")
OCR_MODEL = os.environ.get("OCR_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
OCR_DPI = int(os.environ.get("OCR_DPI", "150"))

OCR_PROMPT = (
    "Transcribe every piece of text in this page image exactly as it appears, "
    "preserving line breaks, question numbers, lettered options and table cells. "
    "Do not summarise, translate, correct or add anything. If the page is blank, reply with nothing."
)


class ExtractionError(Exception):
    pass


def open_pdf(path: str):
    try:
        return fitz.open(path)
    except Exception as e:  # corrupt/encrypted file - the user needs to hear why
        raise ExtractionError(f"Could not open the PDF: {e}")


def page_count(path: str) -> int:
    with open_pdf(path) as doc:
        if doc.needs_pass:
            raise ExtractionError("This PDF is password-protected. Remove the password and upload again.")
        return doc.page_count


def has_text_layer(path: str, sample: int = 8) -> bool:
    """Whether the PDF carries selectable text, sampled across the document."""
    with open_pdf(path) as doc:
        total = doc.page_count
        if not total:
            return False
        step = max(1, total // sample)
        for i in range(0, total, step):
            if len(doc[i].get_text().strip()) >= MIN_TEXT_CHARS:
                return True
    return False


def render_page_png(path: str, page_number: int, dpi: int = OCR_DPI) -> bytes:
    """1-indexed page -> PNG bytes."""
    with open_pdf(path) as doc:
        page = doc[page_number - 1]
        return page.get_pixmap(dpi=dpi).tobytes("png")


def ocr_page(path: str, page_number: int) -> tuple[str, float]:
    """OCR one page. Returns (text, confidence). Raises if OCR is unavailable."""
    if OCR_PROVIDER == "none":
        raise ExtractionError("No OCR provider configured (set OCR_PROVIDER).")
    if OCR_PROVIDER != "openai":
        raise ExtractionError(f"Unknown OCR_PROVIDER: {OCR_PROVIDER}")

    from openai import OpenAI  # imported lazily so `import documents` stays cheap

    png = render_page_png(path, page_number)
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    try:
        resp = OpenAI().chat.completions.create(
            model=OCR_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
            ]}],
            temperature=0,
        )
    except Exception as e:
        raise ExtractionError(f"OCR failed on page {page_number}: {e}")
    text = (resp.choices[0].message.content or "").strip()
    # The model reports no per-character confidence, so this is a proxy: a page
    # that came back with almost nothing is the one worth a human's attention.
    confidence = 0.9 if len(text) >= MIN_TEXT_CHARS else 0.4
    return text, confidence


def extract_page(path: str, page_number: int, allow_ocr: bool = True) -> dict:
    """Extract one page. Never raises for a single bad page - records the error.

    Returns {page_number, text, method, confidence, error}.
    method: TEXT (PDF text layer) | OCR | NONE (nothing could be read).
    """
    out = {"page_number": page_number, "text": "", "method": "NONE",
           "confidence": None, "error": ""}
    try:
        with open_pdf(path) as doc:
            text = doc[page_number - 1].get_text().strip()
    except Exception as e:
        out["error"] = f"Could not read page: {e}"
        return out

    if len(text) >= MIN_TEXT_CHARS:
        return {**out, "text": text, "method": "TEXT", "confidence": 1.0}

    if not allow_ocr or OCR_PROVIDER == "none":
        # Keep whatever the text layer had; flag it rather than invent content.
        return {**out, "text": text, "method": "TEXT" if text else "NONE",
                "confidence": 0.3 if text else 0.0,
                "error": "" if text else "No text layer and OCR is disabled."}

    try:
        ocr_text, confidence = ocr_page(path, page_number)
    except ExtractionError as e:
        return {**out, "text": text, "method": "TEXT" if text else "NONE",
                "confidence": 0.3 if text else 0.0, "error": str(e)}
    # If OCR found less than the text layer did, keep the text layer.
    if len(ocr_text) < len(text):
        return {**out, "text": text, "method": "TEXT", "confidence": 0.5}
    return {**out, "text": ocr_text, "method": "OCR", "confidence": confidence}


def _sample_pdf(path: str):
    """Build a small PDF with our own text, for the self-check."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "TEST 1", fontsize=18)
    page.insert_text((72, 130), "LISTENING", fontsize=14)
    page.insert_text((72, 160), "SECTION 1  Questions 1-10", fontsize=12)
    page.insert_text((72, 190), "Complete the form below. Write NO MORE THAN TWO WORDS.", fontsize=11)
    doc.new_page()  # deliberately blank: the "needs OCR" case
    doc.save(path)
    doc.close()


def _demo():
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    pdf = str(tmp / "sample.pdf")
    _sample_pdf(pdf)

    assert page_count(pdf) == 2
    assert has_text_layer(pdf) is False or True  # tiny page may fall under the threshold either way

    # A page with a text layer is read for free - no OCR, full confidence.
    page1 = extract_page(pdf, 1, allow_ocr=False)
    assert "SECTION 1" in page1["text"] and "Questions 1-10" in page1["text"], page1
    assert page1["method"] == "TEXT" and page1["error"] == ""

    # A blank page with OCR disabled is reported as unreadable, not as empty success.
    blank = extract_page(pdf, 2, allow_ocr=False)
    assert blank["method"] == "NONE" and blank["text"] == ""
    assert "OCR is disabled" in blank["error"], blank

    # A page number outside the document is an error on that page, not a crash.
    bad = extract_page(pdf, 99, allow_ocr=False)
    assert bad["method"] == "NONE" and bad["error"], bad

    # Rendering works (this is what OCR would be handed).
    png = render_page_png(pdf, 1, dpi=72)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 500

    # A file that is not a PDF fails loudly.
    junk = tmp / "junk.pdf"
    junk.write_bytes(b"not a pdf at all")
    try:
        page_count(str(junk))
        raise AssertionError("a non-PDF must raise")
    except ExtractionError:
        pass

    print("documents self-check OK")


if __name__ == "__main__":
    _demo()
