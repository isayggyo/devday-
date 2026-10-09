import hashlib
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .config import get_settings
from .db import database_session
from .material_parser import MaterialError, validate_material, convert_presentation, analyze_pdf
from .models import MaterialDocument, MaterialPage
from .session_manager import owned_session, transition
from .storage import ObjectStore, get_object_store

router = APIRouter(prefix="/sessions/{session_id}/materials", tags=["materials"])


def document_for_user(db, session_id, document_id, user, lock=False):
    owned_session(db, session_id, user)
    query = select(MaterialDocument).where(MaterialDocument.id == document_id, MaterialDocument.session_id == session_id)
    item = db.scalar(query.with_for_update() if lock else query)
    if not item:
        raise HTTPException(404, {"code": "MATERIAL_NOT_FOUND", "message": "자료를 찾을 수 없습니다."})
    return item


def document_view(db, item):
    base = f"/sessions/{item.session_id}/materials/{item.id}"
    pages = db.scalars(select(MaterialPage).where(MaterialPage.document_id == item.id).order_by(MaterialPage.page_number)).all()
    return {"id": str(item.id), "sessionId": str(item.session_id), "filename": item.filename, "fileType": item.file_type,
        "revision": item.revision, "processingStatus": item.processing_status, "sha256": item.sha256,
        "errorCode": item.error_code, "originalUrl": base + "/original", "pages": [
            {"id": str(page.id), "documentId": str(page.document_id), "pageNumber": page.page_number, "text": page.text,
                "description": page.description, "imageRef": base + f"/pages/{page.page_number}/image", "metadata": page.metadata_json} for page in pages]}


def process_document(db, item, data, store):
    prefix = f"sessions/{item.session_id}/materials/{item.id}/r{item.revision}"
    try:
        pdf = data if item.file_type == "pdf" else convert_presentation(data, item.file_type)
        if item.file_type != "pdf":
            store.put(prefix + "/converted.pdf", pdf, "application/pdf")
        pages = analyze_pdf(pdf, store, prefix)
        for page in pages:
            db.add(MaterialPage(document_id=item.id, **page))
        item.processing_status = "needs_analysis" if any(page["metadata_json"]["analysisStatus"] != "ready" for page in pages) else "ready"
        item.error_code = None
        db.commit()
    except Exception as error:
        db.rollback()
        item = db.get(MaterialDocument, item.id)
        item.processing_status = "failed"
        item.error_code = error.code if isinstance(error, MaterialError) else "MATERIAL_PROCESSING_FAILED"
        db.commit()
        # Preserve original binary for a real retry; no fabricated page content.
    return document_view(db, item)


@router.post("", status_code=201)
def upload(session_id: UUID, file: UploadFile = File(...), user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    session = owned_session(db, session_id, user, lock=True)
    if session.status not in {"created", "preparing"}:
        raise HTTPException(409, {"code": "MATERIAL_UPLOAD_CLOSED", "message": "녹음 전에 강의자료를 업로드해 주세요."})
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name[:240]
    data = file.file.read(get_settings().material_max_bytes + 1)
    try:
        file_type = validate_material(filename, data)
    except MaterialError as error:
        raise HTTPException(400, {"code": error.code, "message": str(error)}) from None
    identifier = uuid4()
    key = f"sessions/{session_id}/materials/{identifier}/r1/original.{file_type}"
    try:
        store.put(key, data, "application/pdf" if file_type == "pdf" else "application/octet-stream")
    except Exception:
        raise HTTPException(503, {"code": "OBJECT_STORAGE_UNAVAILABLE", "message": "자료 저장소에 연결할 수 없습니다. 다시 시도해 주세요."}) from None
    if session.status == "created":
        transition(db, session_id, user, "preparing")
    item = MaterialDocument(id=identifier, session_id=session_id, filename=filename, file_type=file_type, revision=1,
        original_ref=key, sha256=hashlib.sha256(data).hexdigest(), processing_status="processing")
    db.add(item)
    try:
        db.commit()
    except Exception:
        db.rollback()
        store.delete(key)
        raise
    return process_document(db, item, data, store)


@router.get("")
def list_materials(session_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    owned_session(db, session_id, user)
    return [document_view(db, item) for item in db.scalars(select(MaterialDocument).where(MaterialDocument.session_id == session_id)).all()]


@router.get("/{document_id}")
def get_material(session_id: UUID, document_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session)):
    return document_view(db, document_for_user(db, session_id, document_id, user))


@router.post("/{document_id}/retry")
def retry_material(session_id: UUID, document_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    session = owned_session(db, session_id, user, lock=True)
    item = document_for_user(db, session_id, document_id, user, lock=True)
    if session.status not in {"created", "preparing"} or item.processing_status != "failed":
        raise HTTPException(409, {"code": "MATERIAL_RETRY_UNAVAILABLE", "message": "현재 자료를 다시 처리할 수 없습니다."})
    try:
        data = store.get(item.original_ref)
    except Exception:
        raise HTTPException(503, {"code": "OBJECT_STORAGE_UNAVAILABLE", "message": "원본 자료를 읽을 수 없습니다."}) from None
    item.processing_status = "processing"
    db.commit()
    return process_document(db, item, data, store)


@router.get("/{document_id}/original")
def original(session_id: UUID, document_id: UUID, user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    item = document_for_user(db, session_id, document_id, user)
    try:
        data = store.get(item.original_ref)
    except Exception:
        raise HTTPException(503, {"code": "OBJECT_STORAGE_UNAVAILABLE", "message": "원본 자료를 읽을 수 없습니다."}) from None
    return Response(data, media_type="application/pdf" if item.file_type == "pdf" else "application/octet-stream")


@router.get("/{document_id}/pages/{page_number}/image")
def image(session_id: UUID, document_id: UUID, page_number: int, user: str = Depends(current_user), db: Session = Depends(database_session), store: ObjectStore = Depends(get_object_store)):
    document_for_user(db, session_id, document_id, user)
    page = db.scalar(select(MaterialPage).where(MaterialPage.document_id == document_id, MaterialPage.page_number == page_number))
    if not page:
        raise HTTPException(404, {"code": "PAGE_NOT_FOUND", "message": "자료 페이지를 찾을 수 없습니다."})
    try:
        data = store.get(page.image_ref)
    except Exception:
        raise HTTPException(503, {"code": "OBJECT_STORAGE_UNAVAILABLE", "message": "페이지 이미지를 읽을 수 없습니다."}) from None
    return Response(data, media_type="image/png")
