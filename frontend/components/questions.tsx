'use client';
import { useEffect, useState, useRef } from 'react';
import { readJson } from '../lib/api';
import type { MaterialDocument } from './materials';
import { VisualExplanation } from './visual-explanation';
import type { Visual } from '../lib/visual';

export type Citation = { sourceType: 'transcript' | 'material'; sourceId: string; revision: number; pageNumber: number | null; excerpt: string };
export type Answer = { id: string; questionId: string; answer: string; citations: Citation[]; groundingStatus: 'grounded' | 'insufficient_context'; needsVisual: boolean };
export type Question = { id: string; sessionId: string; clientQuestionId: string; questionText: string; contextSnapshotId: string; status: string; errorCode: string | null; answer: Answer | null; visual: Visual | null };
type Block = { id: string; text: string; sourceType: string; sourceRef: { startMs?: number; endMs?: number; pageNumber?: number; imageRef?: string; filename?: string }; isPrimaryEvidence: boolean };

export function Evidence({ sessionId, question }: { sessionId: string; question: Question }) {
  const [blocks, setBlocks] = useState<Block[]>([]); const [error, setError] = useState('');
  async function load() {
    try { const result = await readJson<{ bundle: { contextBlocks: Block[] } }>(await fetch(`/api/sessions/${sessionId}/questions/${question.id}/evidence`)); setBlocks(result.bundle.contextBlocks); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '출처를 조회하지 못했습니다.'); }
  }
  return <details onToggle={event => { if (event.currentTarget.open && !blocks.length) void load(); }}><summary>답변 근거와 질문 시점 맥락</summary>
    {error && <p role="alert">{error}</p>}
    {question.answer?.citations.map((ref, index) => {
      const block = blocks.find(item => item.id === ref.sourceId && item.isPrimaryEvidence);
      return <blockquote key={index} data-testid="answer-citation" data-source-id={ref.sourceId}>
        <p>{ref.excerpt}</p><p>{ref.sourceType === 'material' ? `자료 ${ref.pageNumber}페이지` : `전사 ${Math.floor((block?.sourceRef.startMs ?? 0)/1000)}초`} · 버전 {ref.revision}</p>
        {block?.sourceRef.imageRef && <a href={'/api' + block.sourceRef.imageRef} target="_blank" rel="noreferrer">해당 자료 페이지 보기</a>}
      </blockquote>;
    })}
    {blocks.map(block => <details key={block.id}><summary>{block.sourceType === 'summary' ? 'AI 요약 (보조 맥락)' : block.sourceType === 'material' ? `${block.sourceRef.filename} ${block.sourceRef.pageNumber}페이지` : `확정 전사 ${Math.floor((block.sourceRef.startMs ?? 0)/1000)}초`}</summary><p>{block.text}</p></details>)}
  </details>;
}

export function Questions({ sessionId }: { sessionId: string }) {
  const [questions, setQuestions] = useState<Question[]>([]), [documents, setDocuments] = useState<MaterialDocument[]>([]);
  const [text, setText] = useState(''), [selected, setSelected] = useState<string[]>([]), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const pending = useRef<{ clientQuestionId: string; questionText: string; selectedPageIds: string[] } | null>(null);
  const base = `/api/sessions/${sessionId}/questions`;
  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const [items, materials] = await Promise.all([fetch(base).then(readJson<Question[]>), fetch(`/api/sessions/${sessionId}/materials`).then(readJson<MaterialDocument[]>)]);
        if (active) { setQuestions(items); setDocuments(materials); }
      } catch (failure) { if (active) setError(failure instanceof Error ? failure.message : '질문을 조회하지 못했습니다.'); }
    }
    void poll(); const timer = setInterval(() => void poll(), 2500); return () => { active = false; clearInterval(timer); };
  }, [base, sessionId]);
  async function submit() {
    if (busy || !text.trim()) return;
    setBusy(true); setError('');
    const body = pending.current ?? { clientQuestionId: crypto.randomUUID(), questionText: text.trim(), selectedPageIds: selected };
    pending.current = body;
    try {
      const item = await readJson<Question>(await fetch(base, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));
      setQuestions(previous => previous.some(row => row.id === item.id) ? previous : [...previous, item]); setText(''); pending.current = null;
    } catch (failure) { setError(failure instanceof Error ? failure.message : '질문 등록에 실패했습니다. 같은 요청을 다시 보낼 수 있습니다.'); }
    finally { setBusy(false); }
  }
  async function retry(question: Question) {
    try { await readJson(await fetch(base + '/' + question.id + '/retry', { method: 'POST' })); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '답변을 다시 생성하지 못했습니다.'); }
  }
  return <section aria-label="강의 질문"><h2>강의 질문</h2><p>질문을 등록한 시점의 확정 전사와 선택한 자료만 사용합니다. 답변을 기다리는 동안 녹음은 계속됩니다.</p>
    <fieldset disabled={busy || pending.current !== null}><legend>답변에 사용할 자료 페이지 (최대 8개)</legend>{documents.flatMap(document => document.pages.map(page => <label key={page.id} style={{ display: 'block' }}>
      <input data-testid="question-material-page" type="checkbox" checked={selected.includes(page.id)} disabled={!selected.includes(page.id) && selected.length >= 8} onChange={event => setSelected(previous => event.target.checked ? [...previous, page.id] : previous.filter(id => id !== page.id))} />{document.filename} · {page.pageNumber}페이지 · 버전 {document.revision}
    </label>))}</fieldset>
    <label>질문 <textarea data-testid="question-input" value={text} maxLength={2000} disabled={busy || pending.current !== null} onChange={event => setText(event.target.value)} /></label>
    <button data-testid="question-submit" onClick={() => void submit()} disabled={busy || !text.trim()}>{busy ? '질문 등록 중…' : pending.current ? '동일 질문 등록 재시도' : '질문하기'}</button>
    {error && <p role="alert">{error}</p>}
    {questions.map(question => <article key={question.id} data-testid="question-card" data-question-id={question.id} data-status={question.status}>
      <h3>{question.questionText}</h3>{!question.answer && <p>{question.status === 'failed' ? `답변 생성 실패: ${question.errorCode}` : '질문 시점의 근거로 답변을 생성하고 있습니다…'}</p>}
      {!question.answer && <button onClick={() => void retry(question)}>답변 생성 재시도</button>}
      {question.answer && <><p data-testid="question-answer" style={{ whiteSpace: 'pre-wrap' }}>{question.answer.answer}</p><p>{question.answer.groundingStatus === 'grounded' ? '강의 근거 확인됨 · AI 설명' : '질문 시점의 강의 근거가 부족합니다'}</p><Evidence sessionId={sessionId} question={question} />
        {question.answer.groundingStatus === 'grounded' && <VisualExplanation sessionId={sessionId} questionId={question.id} visual={question.visual} />}</>}
    </article>)}
  </section>;
}
