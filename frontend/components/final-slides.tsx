'use client';
import { useEffect, useState } from 'react';
import { readJson } from '../lib/api';
import { slideContent, type FinalSlide } from '../lib/slides';
import type { LectureSession } from './session-manager';

type Evidence = { evidenceId: string; questionText: string; isPreviousLecture: boolean; lectureTitle: string; sessionId: string };
type FinalResult = { status: string; sessionStatus?: string; slides: FinalSlide[]; errorCode?: string; challengeStatus?: string; challengeError?: string;
  evidenceBundle?: { questions: Evidence[] }; sourceIndex?: { sourceId: string; sessionId: string; revision: number; filename?: string; documentId?: string; pageNumber?: number; startMs?: number }[] };

export function FinalSlides({ session, onStatus }: { session: LectureSession; onStatus: (id: string, status: string) => void }) {
  const [result, setResult] = useState<FinalResult>({ status: 'not_started', slides: [] }), [error, setError] = useState(''), [busy, setBusy] = useState(false), [solutions, setSolutions] = useState(false);
  const base = `/api/sessions/${session.id}`;
  const slides = result.slides ?? [];
  useEffect(() => {
    let active = true;
    const poll = async () => { try { const state = await fetch(base + '/synthesis').then(readJson<FinalResult>); if (active) { setResult(state); if (state.sessionStatus && state.status !== 'not_started') onStatus(session.id, state.sessionStatus); } } catch (failure) { if (active) setError(failure instanceof Error ? failure.message : '최종 결과 조회 실패'); } };
    void poll(); const timer = setInterval(() => void poll(), 3000); return () => { active = false; clearInterval(timer); };
  }, [base, session.id, onStatus]);
  async function retry(challenge: boolean) {
    setBusy(true); setError('');
    try { setResult(await readJson<FinalResult>(await fetch(base + (challenge ? '/challenge/retry' : '/finish'), { method: 'POST' }))); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '생성 재시도 실패'); }
    finally { setBusy(false); }
  }
  async function exportPdf() {
    setBusy(true); setError('');
    try {
      const response = await fetch(base + '/slides/pdf?include_answers=' + solutions);
      if (!response.ok) { await readJson(response); return; }
      const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a'); link.href = url; link.download = `lecture-${session.id}.pdf`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'PDF 내보내기 실패'); }
    finally { setBusy(false); }
  }
  return <section aria-label="최종 슬라이드" data-testid="final-slides" data-status={result.status}><h2>최종 학습 슬라이드</h2>
    {result.status === 'empty' && <div className="final-empty" role="status"><h3>요약할 내용이 없어요</h3><p>녹음은 종료됐어요. 기록된 강의 내용이 없어 슬라이드를 만들지 않았어요.</p></div>}
    {result.status === 'not_started' && <p>강의를 종료하면 질문·학습 반응을 반영한 슬라이드와 응용 문제를 생성합니다.</p>}
    {['queued', 'generating', 'generating_challenge'].includes(result.status) && <p role="status">{result.status === 'generating_challenge' ? '본문 슬라이드가 저장됐습니다. 마지막 응용 문제를 추가하고 있습니다…' : '강의 내용과 학습 증거로 슬라이드를 생성하고 있습니다…'}</p>}
    {result.status === 'failed' && <><p role="alert">슬라이드 생성 실패: {result.errorCode}</p><button disabled={busy} onClick={() => void retry(false)}>슬라이드 생성 재시도</button></>}
    {result.challengeStatus === 'failed' && <><p role="status">응용 문제 생성 실패: {result.challengeError}. 본문 슬라이드는 보존됩니다.</p><button disabled={busy} onClick={() => void retry(true)}>응용 문제만 다시 생성</button></>}
    {error && <p role="alert">{error}</p>}
    {!!slides.length && <div><label><input type="checkbox" checked={solutions} onChange={event => setSolutions(event.target.checked)} />PDF에 힌트·정답 포함</label><button data-testid="final-export-pdf" disabled={busy} onClick={() => void exportPdf()}>PDF 내보내기</button></div>}
    {slides.map(slide => <article key={slide.id} className="final-slide" data-testid="generated-slide" data-slide-id={slide.id} data-kind={slide.kind}>
      <h3>{slide.kind === 'challenge' ? '응용 문제 · ' : ''}{slide.title}</h3>{slideContent(slide)}
      {!!slide.evidenceRefs.length && <details><summary>개인화에 반영된 질문</summary>{slide.evidenceRefs.map(id => {
        const evidence = result.evidenceBundle?.questions.find(item => item.evidenceId === id);
        return <p key={id}>{evidence?.isPreviousLecture ? `이전 강의 (${evidence.lectureTitle})` : '이번 강의'}: <a href={`/?session=${evidence?.sessionId ?? session.id}#question-${id}`}>{evidence?.questionText ?? id}</a></p>;
      })}</details>}
      <details><summary>강의·자료 출처</summary>{slide.sourceRefs.map((ref, index) => {
        const source = result.sourceIndex?.find(item => item.sourceId === ref.sourceId && item.revision === ref.revision);
        return <blockquote key={index} data-testid="slide-source"><p>{source?.filename ? `${source.filename} · ${ref.pageNumber}페이지` : `전사 ${Math.floor((source?.startMs ?? 0)/1000)}초`} · 버전 {ref.revision}</p><p>{ref.excerpt}</p>
          {source?.documentId && <a href={`/api/sessions/${source.sessionId}/materials/${source.documentId}/pages/${ref.pageNumber}/image`} target="_blank" rel="noreferrer">원본 자료 페이지</a>}
        </blockquote>;
      })}</details>
    </article>)}
  </section>;
}
