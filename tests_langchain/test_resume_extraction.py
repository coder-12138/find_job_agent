"""Layered PDF extraction, evidence and OCR quality-gate tests."""

import fitz

from job_application_agent_langchain.resume_ingestion import ResumeExtractor


def make_text_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_textbox(fitz.Rect(50, 50, 545, 792), text, fontsize=12)
    payload = document.tobytes()
    document.close()
    return payload


def make_image_only_pdf(text: str) -> bytes:
    source = fitz.open()
    source_page = source.new_page(width=900, height=300)
    source_page.insert_text((35, 100), text, fontsize=34, color=(0, 0, 0))
    image = source_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
    source.close()

    target = fitz.open()
    target_page = target.new_page(width=900, height=300)
    target_page.insert_image(target_page.rect, stream=image)
    payload = target.tobytes()
    target.close()
    return payload


def test_text_layer_produces_page_evidence_and_contact_proposals():
    pdf = make_text_pdf(
        "Name: Alice Example\nEmail alice@example.com\nPhone 13800000000\n"
        "Skills\nPython SQL Reliability Engineering Distributed Systems"
    )

    extraction = ResumeExtractor(minimum_page_characters=20).extract(pdf)

    assert extraction.pages[0].method == "text_layer"
    assert extraction.pages[0].evidence
    assert extraction.quality.ocr_pages == ()
    fields = {field.field_key: field for field in extraction.proposed_fields}
    assert fields["email"].value == "alice@example.com"
    assert fields["phone"].value == "13800000000"
    assert fields["full_name"].value == "Alice Example"
    assert fields["email"].evidence[0].page == 1
    assert all(0 <= coordinate <= 1 for coordinate in fields["email"].evidence[0].bbox)


def test_low_text_page_uses_ocr_fallback_with_normalized_evidence():
    class FakeOcr:
        def __call__(self, image):
            assert image.startswith(b"\x89PNG")
            return (
                [
                    [
                        [[20, 20], [500, 20], [500, 60], [20, 60]],
                        "Email scan@example.com Phone 13900000000",
                        0.93,
                    ]
                ],
                [0.01, 0.01, 0.01],
            )

    blank_pdf = make_text_pdf("image")
    extraction = ResumeExtractor(
        minimum_page_characters=60,
        ocr_factory=FakeOcr,
    ).extract(blank_pdf)

    assert extraction.pages[0].method == "ocr"
    assert extraction.quality.ocr_pages == (1,)
    assert extraction.quality.needs_review is True
    fields = {field.field_key: field.value for field in extraction.proposed_fields}
    assert fields["email"] == "scan@example.com"
    assert fields["phone"] == "13900000000"
    assert all(0 <= value <= 1 for value in extraction.pages[0].evidence[0].bbox)


def test_actual_local_ocr_reads_an_image_only_pdf():
    pdf = make_image_only_pdf("Email ocr@example.com Phone 13700000000")

    extraction = ResumeExtractor(minimum_page_characters=20).extract(pdf)

    assert extraction.pages[0].method == "ocr"
    assert "ocr@example.com" in extraction.pages[0].text
    assert extraction.quality.ocr_pages == (1,)
