import hashlib
import io
from pathlib import Path
import subprocess
from uuid import UUID

import pymupdf
import pytest
from pptx import Presentation

from backend.app import app
from backend.config import get_settings, ROOT
from backend.material_parser import validate_material, MaterialError
from backend.models import MaterialDocument
from backend.storage import ObjectStore, get_object_store
from backend.tests.test_sessions import environment, create


@pytest.fixture
def materials(environment):
    client, factory, user, other = environment
    store = ObjectStore(get_settings().s3_test_bucket)
    store.initialize()
    app.dependency_overrides[get_object_store] = lambda: store
    session = create(client, user)
    try:
        yield client, factory, user, other, session, store
    finally:
        store.delete_prefix(f"sessions/{session['id']}/")
        app.dependency_overrides.pop(get_object_store, None)


def upload(client, user, session, data, filename):
    return client.post(f"/sessions/{session['id']}/materials", headers={"X-Dev-User-Id": user}, files={"file": (filename, data)})


def test_real_pdf_pages_original_and_access_isolation(materials):
    client, factory, user, other, session, store = materials
    data = (ROOT / "e2e/fixtures/lecture.pdf").read_bytes()
    response = upload(client, user, session, data, "lecture.pdf")
    assert response.status_code == 201
    document = response.json()
    assert document["processingStatus"] == "ready", document
    assert [page["pageNumber"] for page in document["pages"]] == [1, 2]
    assert "retrieval" in document["pages"][0]["text"].lower()
    assert document["sha256"] == hashlib.sha256(data).hexdigest()
    headers = {"X-Dev-User-Id": user}
    assert client.get(document["originalUrl"], headers=headers).content == data
    image = client.get(document["pages"][0]["imageRef"], headers=headers)
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    with factory() as db:
        row = db.get(MaterialDocument, UUID(document["id"]))
        assert store.get(row.original_ref) == data
    for path in [document["originalUrl"], document["pages"][0]["imageRef"], f"/sessions/{session['id']}/materials"]:
        assert client.get(path, headers={"X-Dev-User-Id": other}).status_code == 404
    unrelated = create(client, user)
    assert client.get(f"/sessions/{unrelated['id']}/materials/{document['id']}", headers=headers).status_code == 404
    assert client.get(f"/sessions/{session['id']}", headers=headers).json()["status"] == "preparing"


def test_textless_page_marked_for_analysis_and_vectors_preserved(materials):
    client, _, user, _, session, _ = materials
    document = pymupdf.open()
    page = document.new_page()
    page.draw_rect(pymupdf.Rect(40, 40, 140, 100), color=(0, 0, 1))
    result = upload(client, user, session, document.tobytes(), "diagram.pdf").json()
    document.close()
    assert result["processingStatus"] == "needs_analysis"
    assert result["pages"][0]["text"] == ""
    assert result["pages"][0]["metadata"]["vectorDrawings"]


@pytest.mark.parametrize("filename,data", [("lecture.exe", b"anything"), ("lecture.pdf", b"not pdf"), ("lecture.pptx", b"not zip"), ("lecture.ppt", b"not ole"), ("lecture.pdf", b"")])
def test_invalid_files_do_not_create_materials(materials, filename, data):
    client, _, user, _, session, _ = materials
    result = upload(client, user, session, data, filename)
    assert result.status_code == 400 and result.json()["detail"]["code"]
    assert client.get(f"/sessions/{session['id']}/materials", headers={"X-Dev-User-Id": user}).json() == []


def test_size_and_encrypted_pdf_rejected(monkeypatch):
    monkeypatch.setattr(get_settings(), "material_max_bytes", 10)
    with pytest.raises(MaterialError, match="크기"):
        validate_material("lecture.pdf", b"%PDF-" + b"x" * 20)


def test_table_and_formula_original_representation_preserved(materials):
    client, _, user, _, session, _ = materials
    source = pymupdf.open()
    page = source.new_page()
    for x in [60, 160, 260]:
        page.draw_line((x, 100), (x, 180))
    for y in [100, 140, 180]:
        page.draw_line((60, y), (260, y))
    for x, y, text in [(80, 125, "Topic"), (180, 125, "Score"), (80, 165, "Recall"), (180, 165, "90")]:
        page.insert_text((x, y), text)
    page.insert_text((60, 220), "F = m a", fontsize=16)
    item = upload(client, user, session, source.tobytes(), "table-formula.pdf").json()
    source.close()
    assert item["processingStatus"] == "ready", item
    metadata = item["pages"][0]["metadata"]
    assert metadata["tables"][0]["cells"] == [["Topic", "Score"], ["Recall", "90"]]
    assert "F = m a" in item["pages"][0]["text"]
    assert metadata["textBlocks"] and metadata["vectorDrawings"]


def test_encrypted_pdf_cannot_be_parsed_without_user_password():
    source = pymupdf.open()
    source.new_page()
    data = source.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="password")
    source.close()
    with pytest.raises(MaterialError) as error:
        validate_material("encrypted.pdf", data)
    assert error.value.code == "ENCRYPTED_PDF"


def test_pptx_real_libreoffice_conversion(materials):
    client, _, user, _, session, _ = materials
    deck = Presentation()
    for title in ["Retrieval practice", "Spaced practice"]:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = "Real lecture material for conversion"
    output = io.BytesIO()
    deck.save(output)
    result = upload(client, user, session, output.getvalue(), "lecture.pptx")
    assert result.status_code == 201
    document = result.json()
    assert document["processingStatus"] == "ready", document
    assert len(document["pages"]) == 2
    assert "Retrieval practice" in document["pages"][0]["text"]
    assert client.get(document["originalUrl"], headers={"X-Dev-User-Id": user}).content == output.getvalue()


def test_legacy_ppt_real_conversion(materials, tmp_path):
    client, _, user, _, session, _ = materials
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Legacy lecture presentation"
    source = tmp_path / "legacy.pptx"
    deck.save(source)
    subprocess.run([get_settings().libreoffice_path, "-env:UserInstallation=" + (tmp_path / "profile").as_uri(), "--headless", "--convert-to", "ppt:MS PowerPoint 97", "--outdir", str(tmp_path), str(source)], check=True, timeout=120, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    legacy = (tmp_path / "legacy.ppt").read_bytes()
    item = upload(client, user, session, legacy, "legacy.ppt").json()
    assert item["processingStatus"] == "ready", item
    assert len(item["pages"]) == 1 and "Legacy lecture presentation" in item["pages"][0]["text"]


def test_unavailable_storage_rejects_upload_without_committing_document(materials, monkeypatch):
    client, _, user, _, session, store = materials
    def unavailable(*args):
        raise ConnectionError("Unavailable")
    monkeypatch.setattr(store, "put", unavailable)
    result = upload(client, user, session, (ROOT / "e2e/fixtures/lecture.pdf").read_bytes(), "lecture.pdf")
    assert result.status_code == 503
    assert result.json()["detail"]["code"] == "OBJECT_STORAGE_UNAVAILABLE"
    assert client.get(f"/sessions/{session['id']}/materials", headers={"X-Dev-User-Id": user}).json() == []


def test_storage_failure_and_real_retry(materials, monkeypatch):
    client, _, user, _, session, store = materials
    data = (ROOT / "e2e/fixtures/lecture.pdf").read_bytes()
    real_put = store.put

    def broken_pages(key, data, mime):
        if "/pages/" in key:
            raise ConnectionError("Storage interruption")
        return real_put(key, data, mime)

    monkeypatch.setattr(store, "put", broken_pages)
    item = upload(client, user, session, data, "lecture.pdf").json()
    assert item["processingStatus"] == "failed" and item["pages"] == []
    assert client.get(item["originalUrl"], headers={"X-Dev-User-Id": user}).content == data
    monkeypatch.setattr(store, "put", real_put)
    result = client.post(f"/sessions/{session['id']}/materials/{item['id']}/retry", headers={"X-Dev-User-Id": user}).json()
    assert result["processingStatus"] == "ready" and len(result["pages"]) == 2
