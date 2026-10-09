'use client';
import { useEffect, useState } from 'react';
import { readJson } from '../lib/api';
import type { LectureSession } from './session-manager';

export function RecordingInput({ session, initialFile, onImported, onQuestion }: { session: LectureSession | null; initialFile?: File | null; onImported: (session: LectureSession) => void; onQuestion: (text: string) => void }) {
  const [file, setFile] = useState<File | null>(null), [timeline, setTimeline] = useState<File | null>(null);
  const [lectures, setLectures] = useState<string[]>([]), [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const info = session?.recordingInput;
  const available = !!session && ['created', 'preparing'].includes(session.status) && !busy;
  async function choose(value: File | null) {
    setFile(value); setLectures([]); setSelected(''); setError('');
    if (!value) return;
    if (value.size > 2*1024*1024) { setError('전사 JSON은 최대 2MB입니다.'); return; }
    try {
      const data = JSON.parse((await value.text()).replace(/^\uFEFF/, ''));
      if (Array.isArray(data)) { setError('슬라이드 시간표는 아래 시간표 항목에서 선택하고 전사 JSON을 먼저 가져와 주세요.'); return; }
      if (Array.isArray(data.lectures)) { const ids = data.lectures.map((item: { lecture_id?: unknown }) => item?.lecture_id).filter((id: unknown): id is string => typeof id === 'string'); setLectures(ids); setSelected(ids[0] ?? ''); }
    } catch { setError('JSON 파일을 읽을 수 없습니다.'); }
  }
  useEffect(() => { setTimeline(null); void choose(initialFile?.name.toLowerCase().endsWith('.json') ? initialFile : null); }, [session?.id]);
  async function upload() {
    if (!session || (!file && !info)) return;
    setBusy(true); setError(''); const body = new FormData();
    if (info) { if (!timeline) { setBusy(false); return; } body.set('file', timeline); }
    else { body.set('file', file!); if (selected) body.set('lecture_id', selected); if (timeline) body.set('timeline', timeline); }
    try {
      const result = await readJson<{ session: LectureSession }>(await fetch(`/api/sessions/${session.id}/recording-json${info ? '/timeline' : ''}`, { method: 'POST', body }));
      onImported(result.session); setFile(null); setTimeline(null);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'JSON 입력에 실패했습니다.'); }
    finally { setBusy(false); }
  }
  return <section aria-label="녹음 JSON 입력"><h2>녹음 전사 JSON</h2><p>전사 텍스트와 시간 정보를 가져옵니다. 오디오 녹음이나 실시간 STT 결과로 표시하지 않습니다.</p>
    {!info && <><label>전사 JSON <input data-testid="recording-json-file" type="file" accept=".json,application/json" disabled={!available} onChange={event => void choose(event.target.files?.[0] ?? null)} /></label>
      {file && <p>{file.name}</p>}{!!lectures.length && <label>합본에서 가져올 강의 <select data-testid="recording-json-lecture" value={selected} disabled={!available} onChange={event => setSelected(event.target.value)}>{lectures.map(id => <option key={id} value={id}>{id}</option>)}</select></label>}</>}
    <label>슬라이드 시간표 JSON (선택) <input data-testid="recording-timeline-file" type="file" accept=".json,application/json" disabled={!available} onChange={event => setTimeline(event.target.files?.[0] ?? null)} /></label>
    <button data-testid="recording-json-import" disabled={!available || (info ? !timeline : !file)} onClick={() => void upload()}>{busy ? '가져오는 중…' : info ? '시간표 연결' : '전사 JSON 가져오기'}</button>
    {error && <p role="alert">{error}</p>}
    {info && <div data-testid="recording-json-info"><p>업로드 전사 · {info.filename} · {info.lectureId} · {info.segmentCount}개 구간</p><a href={`/api/sessions/${session!.id}/recording-json/original`} target="_blank" rel="noreferrer">전사 JSON 원본</a>
      {!!info.timeline.length && <details><summary>슬라이드 시간표 · {info.timelineFilename}</summary><a href={`/api/sessions/${session!.id}/recording-json/original?timeline=true`} target="_blank" rel="noreferrer">시간표 원본</a>{info.timeline.map(item => <p key={item.slide}>{item.startMs/1000}–{item.endMs/1000}초 · 슬라이드 {item.slide} · {item.title}</p>)}</details>}
      {info.questionExamples.map((item, index) => <div key={index}><p>JSON의 질문 예시 · {item.timestampMs/1000}초: {item.text}</p><button data-testid="import-question-example" onClick={() => onQuestion(item.text)}>질문 입력창에 가져오기</button></div>)}
    </div>}
  </section>;
}
