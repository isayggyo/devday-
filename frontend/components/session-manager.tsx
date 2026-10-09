'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { readJson } from '../lib/api';

export type LectureSession = {
  id: string; title: string; status: string; userId: string;
  createdAt: string; startedAt: string | null; endedAt: string | null;
};

const labels: Record<string, string> = { created: '생성됨', preparing: '준비 중', recording: '녹음 중', finalizing: '녹음 마무리', processing: '학습 자료 생성 중', completed: '완료', failed: '실패' };

export function SessionManager({ onSelect, selected }: { onSelect: (session: LectureSession) => void; selected: LectureSession | null }) {
  const [items, setItems] = useState<LectureSession[]>([]);
  const [title, setTitle] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const select = useCallback((item: LectureSession) => {
    onSelect(item);
    const url = new URL(window.location.href);
    url.searchParams.set('session', item.id);
    window.history.replaceState(null, '', url);
  }, [onSelect]);

  const load = useCallback(async () => {
    setError('');
    try {
      const list = await readJson<LectureSession[]>(await fetch('/api/sessions'));
      setItems(list);
      const id = new URL(window.location.href).searchParams.get('session');
      if (id) select(await readJson<LectureSession>(await fetch('/api/sessions/' + encodeURIComponent(id))));
    } catch (failure) { setError(failure instanceof Error ? failure.message : '강의 조회에 실패했습니다.'); }
  }, [select]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (selected) setItems(previous => previous.map(item => item.id === selected.id ? selected : item)); }, [selected]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const item = await readJson<LectureSession>(await fetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) }));
      setItems(previous => [item, ...previous]); select(item); setTitle('');
    } catch (failure) { setError(failure instanceof Error ? failure.message : '강의 생성에 실패했습니다.'); }
    finally { setBusy(false); }
  }

  return <section aria-label="강의 세션">
    <h2>내 강의</h2>
    <p>현재 로컬 개발용 임시 사용자로 사용 중입니다.</p>
    <form onSubmit={create}>
      <label>강의 제목 <input data-testid="session-title" value={title} onChange={event => setTitle(event.target.value)} maxLength={200} required /></label>
      <button data-testid="session-create" disabled={busy || !title.trim()}>{busy ? '생성 중…' : '새 강의 만들기'}</button>
    </form>
    {error && <p role="alert">{error} <button onClick={() => void load()}>다시 불러오기</button></p>}
    <ul>{items.map(item => <li key={item.id}>
      <button data-testid="session-select" data-session-id={item.id} onClick={async () => {
        setError('');
        try { select(await readJson<LectureSession>(await fetch('/api/sessions/' + item.id))); }
        catch (failure) { setError(failure instanceof Error ? failure.message : '강의 조회에 실패했습니다.'); }
      }}>{item.title} · {labels[item.status] ?? item.status}</button></li>)}</ul>
    <p data-testid="session-state" data-session-id={selected?.id ?? ''} data-state={selected && ['created', 'preparing'].includes(selected.status) ? 'idle' : selected?.status === 'finalizing' ? 'stopped' : selected?.status === 'completed' ? 'ended' : selected?.status ?? 'idle'}>
      {selected ? `${selected.title} · ${labels[selected.status] ?? selected.status}` : '강의를 생성하거나 선택해 주세요.'}
    </p>
  </section>;
}
