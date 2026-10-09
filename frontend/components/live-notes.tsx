'use client';
import { useEffect, useState } from 'react';
import { readJson } from '../lib/api';
type Note = { id: string; summary: string; startMs: number; endMs: number; revision: number; status: string; errorCode: string | null; sourceRefs: { sourceId: string; excerpt: string }[] };
export function LiveNotes({ sessionId }: { sessionId: string }) {
  const [notes, setNotes] = useState<Note[]>([]), [error, setError] = useState('');
  const [checks,setChecks]=useState<Record<string,string>>({});
  const base = '/api/sessions/' + sessionId + '/notes';
  useEffect(() => {
    let active = true;
    const load = async () => { try { const result = await readJson<Note[]>(await fetch(base)); if (active) { setNotes(result); setError(''); } } catch (error) { if (active) setError(error instanceof Error ? error.message : '노트 조회 실패'); } };
    void load(); const timer = setInterval(() => void load(), 2500); return () => { active = false; clearInterval(timer); };
  }, [base]);
  return <section aria-label="강의 요약"><h2>강의 요약 노트</h2><button onClick={() => void fetch(base + '/refresh', { method: 'POST' }).then(readJson).catch(error => setError(error.message))}>요약 갱신·재시도</button>
    {error && <p role="status">{error}</p>}{!notes.length && <p>확정 발화가 누적되면 요약이 추가됩니다.</p>}
    {notes.map(note => <article key={note.id} data-testid="live-note" data-status={note.status} data-revision={note.revision}><h3>{Math.floor(note.startMs / 1000)}–{Math.floor(note.endMs / 1000)}초 · 버전 {note.revision}</h3><p>{note.summary}</p>
      {note.status === 'generating' && <p>요약을 갱신하고 있습니다.</p>}{note.status === 'failed' && <p>요약 실패 · {note.errorCode} · 녹음과 전사는 유지됩니다.</p>}
      <div className="understanding-question"><span className="octi-face"><img src="/mascots/gyeoli-v3.png" alt="옥티"/></span>이 구간, 얼마나 이해했나요?</div>
      {checks[note.id]==='이해했어요'?<p className="understanding-check">✓ 이해했어요</p>:<div className="understanding-buttons">{['이해했어요','조금 헷갈려요','이해하기 어려워요'].map(label=><button key={label} aria-pressed={checks[note.id]===label} onClick={()=>setChecks(previous=>({...previous,[note.id]:label}))}>{label}</button>)}</div>}
      <details><summary>원본 발화 출처</summary>{note.sourceRefs.map((ref, index) => <blockquote key={index}>{ref.excerpt} <small>{ref.sourceId}</small></blockquote>)}</details></article>)}
  </section>;
}
