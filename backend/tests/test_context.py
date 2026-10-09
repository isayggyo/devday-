from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from backend.context import freeze_context, WindowContextProvider, primary_evidence
from backend.models import TranscriptSegment, ContextSnapshot, MaterialDocument, MaterialPage
from backend.tests.test_notes import seed
from backend.tests.test_sessions import create


def test_frozen_bundle_blocks_future_and_changed_evidence(environment):
    _, factory, user, _ = environment
    session_id = UUID(seed(environment)['id'])
    with factory() as db:
        snapshot = freeze_context(db, session_id, user, uuid4()); db.commit(); identifier = snapshot.snapshot_id
        bundle = WindowContextProvider().getForQuestion('unit question', snapshot)
        assert len(primary_evidence(bundle)) == 2 and bundle.coverage['sufficient']
        original = bundle.model_dump()
        row = db.scalar(select(TranscriptSegment).where(TranscriptSegment.session_id == session_id))
        row.text = 'changed after snapshot'; row.committed_at = datetime.now(timezone.utc) + timedelta(seconds=2); db.commit()
    with factory() as db:
        loaded = db.get(ContextSnapshot, identifier)
        assert WindowContextProvider().getForQuestion('unit question', loaded).model_dump() == original
        assert all('changed' not in block['text'] for block in loaded.frozen_blocks)


def test_material_revision_and_owner_are_frozen(environment):
    client, factory, user, other = environment
    session_id = UUID(create(client, user)['id'])
    with factory() as db:
        doc = MaterialDocument(session_id=session_id, filename='unit.pdf', file_type='pdf', revision=2,
            processing_status='ready', original_ref='unit', sha256='0'*64); db.add(doc); db.flush()
        page = MaterialPage(document_id=doc.id, page_number=1, text='Unit material evidence', description='', image_ref='unit-image', metadata_json={})
        db.add(page); db.flush()
        snapshot = freeze_context(db, session_id, user, uuid4(), [page.id]); db.commit()
        assert snapshot.material_revisions[str(doc.id)] == 2
        doc.revision = 3; page.text = 'new version'; db.commit()
        assert snapshot.frozen_blocks[0]['text'] == 'Unit material evidence'
        assert snapshot.frozen_blocks[0]['sourceRef']['revision'] == 2
        with pytest.raises(HTTPException): freeze_context(db, session_id, other, uuid4(), [page.id])
        db.rollback()
        another = UUID(create(client, user)['id'])
        with pytest.raises(HTTPException): freeze_context(db, another, user, uuid4(), [page.id])


def test_empty_and_late_commit_context(environment):
    client, factory, user, _ = environment
    empty = UUID(create(client, user)['id'])
    with factory() as db:
        snapshot = freeze_context(db, empty, user, uuid4()); db.commit()
        assert not snapshot.coverage['sufficient'] and 'INSUFFICIENT_CONTEXT' in snapshot.diagnostics
    session_id = UUID(seed(environment)['id'])
    with factory() as db:
        row = db.scalar(select(TranscriptSegment).where(TranscriptSegment.session_id == session_id, TranscriptSegment.sequence == 0))
        row.committed_at = datetime.now(timezone.utc) + timedelta(seconds=10); db.commit()
        snapshot = freeze_context(db, session_id, user, uuid4()); db.commit()
        assert snapshot.transcript_high_watermark == 1
        assert len(primary_evidence(WindowContextProvider().getForQuestion('', snapshot))) == 1
