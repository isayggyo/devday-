'use client';

import { useEffect, useState } from 'react';
import { readJson } from '../lib/api';
import type { LectureSession } from './session-manager';

export type MaterialPage = { id: string; documentId: string; pageNumber: number; text: string; description: string; imageRef: string; metadata: { analysisStatus: string; tables: unknown[]; images: unknown[] } };
export type MaterialDocument = { id: string; sessionId: string; filename: string; fileType: string; revision: number; processingStatus: string; errorCode: string | null; originalUrl: string; sha256: string; pages: MaterialPage[] };
const localUrl = (url: string) => '/api' + url;

export function Materials({ session, onPrepared, initialFile }: { initialFile?: File | null; session: LectureSession | null; onPrepared: (sessionId: string) => void }) {
  const [documents, setDocuments] = useState<MaterialDocument[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pageNumbers, setPageNumbers] = useState<Record<string, number>>({});
  const base = session ? '/api/sessions/' + session.id + '/materials' : '';
  useEffect(() => {
    let active = true;
    setDocuments([]); setFile(initialFile??null); setError(''); setPageNumbers({});
    if (base) void fetch(base).then(readJson<MaterialDocument[]>).then(items => { if (active) setDocuments(items); }).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [base]);

  async function upload() {
    if (!file || !session) return;
    const sessionId = session.id;
    setBusy(true); setError('');
    const body = new FormData(); body.set('file', file);
    try {
      const item = await readJson<MaterialDocument>(await fetch(base, { method: 'POST', body }));
      if (item.sessionId === sessionId) { setDocuments(previous => [...previous, item]); setFile(null); onPrepared(sessionId); }
      if (item.processingStatus === 'failed') setError('자료 처리에 실패했습니다: ' + item.errorCode);
    } catch (failure) { setError(failure instanceof Error ? failure.message : '자료 업로드에 실패했습니다.'); }
    finally { setBusy(false); }
  }

  async function retry(document: MaterialDocument) {
    setBusy(true); setError('');
    try {
      const item = await readJson<MaterialDocument>(await fetch(base + '/' + document.id + '/retry', { method: 'POST' }));
      setDocuments(previous => previous.map(existing => existing.id === item.id ? item : existing));
      if (item.processingStatus === 'failed') setError('다시 처리하지 못했습니다: ' + item.errorCode);
    } catch (failure) { setError(failure instanceof Error ? failure.message : '재처리에 실패했습니다.'); }
    finally { setBusy(false); }
  }

  return <section aria-label="강의자료">
    <h2>강의자료</h2>
    {!session && <p>강의를 먼저 생성하거나 선택해 주세요.</p>}
    <label>PDF / PPT 선택 <input key={session?.id} data-testid="lecture-pdf-input" type="file" accept=".pdf,.ppt,.pptx" disabled={!session || busy || !['created', 'preparing'].includes(session.status)} onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
    <button data-testid="lecture-upload" disabled={!file || busy} onClick={() => void upload()}>{busy ? '업로드 및 페이지 분석 중…' : '자료 업로드'}</button>
    <p>파일당 30MB, 최대 200페이지. 원본·페이지 이미지·추출 텍스트를 보관합니다.</p>
    {error && <p role="alert">{error}</p>}
    {documents.map(document => {
      const index = pageNumbers[document.id] ?? 0;
      const page = document.pages[index];
      return <article key={document.id} data-testid="lecture-document" data-document-id={document.id} data-filename={document.filename}>
        <h3>{document.filename}</h3>
        <p>버전 {document.revision} · {document.pages.length}페이지 · {document.processingStatus === 'ready' ? '분석 완료' : document.processingStatus === 'needs_analysis' ? '일부 페이지의 추가 시각 분석 필요' : document.processingStatus === 'failed' ? '처리 실패' : '분석 중'}</p>
        <a href={localUrl(document.originalUrl)} target="_blank" rel="noreferrer">원본 열기</a>
        {document.processingStatus === 'failed' && <button disabled={busy} onClick={() => void retry(document)}>자료 다시 처리</button>}
        {page && <>
          <nav aria-label="자료 페이지"><button disabled={index === 0} onClick={() => setPageNumbers(previous => ({ ...previous, [document.id]: index - 1 }))}>이전</button>
            <span>{page.pageNumber} / {document.pages.length}</span><button data-testid="material-next-page" disabled={index + 1 >= document.pages.length} onClick={() => setPageNumbers(previous => ({ ...previous, [document.id]: index + 1 }))}>다음</button></nav>
          <img data-testid="material-page-image" src={localUrl(page.imageRef)} alt={`${document.filename} ${page.pageNumber}페이지 원본 이미지`} style={{ maxWidth: '100%', maxHeight: 640, objectFit: 'contain' }} />
          {page.metadata.analysisStatus === 'needs_analysis' && <p>이 페이지는 추가 시각 분석이 필요합니다. 원본 이미지를 참고해 주세요.</p>}
          <details><summary>추출 텍스트와 페이지 정보</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{page.text || '추출할 텍스트가 없습니다.'}</pre><p>표 {page.metadata.tables.length}개 · 이미지 {page.metadata.images.length}개</p></details>
        </>}
      </article>;
    })}
  </section>;
}
