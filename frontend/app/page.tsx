'use client';

import { useCallback, useState } from 'react';
import { BackendStatus } from '../components/backend-status';
import { SessionManager, type LectureSession } from '../components/session-manager';
import { Materials } from '../components/materials';
import { AudioRecorder } from '../components/audio-recorder';
import { LiveNotes } from '../components/live-notes';

export default function Page() {
  const [session, setSession] = useState<LectureSession | null>(null);
  const selectSession = useCallback((item: LectureSession) => setSession(item), []);
  const prepared = useCallback((sessionId: string) => setSession(previous => previous?.id === sessionId ? { ...previous, status: 'preparing' } : previous), []);

  return <main data-testid="lecture-app">
    <h1>강의 워크스페이스</h1>
    <BackendStatus />
    <p>강의자료와 실시간 전사를 바탕으로 노트와 질문 답변을 확인하세요.</p>
    <SessionManager onSelect={selectSession} selected={session} />
    <Materials key={'materials-' + (session?.id ?? 'none')} session={session} onPrepared={prepared} />
    <AudioRecorder key={'audio-' + (session?.id ?? 'none')} session={session} onSession={selectSession} />
    {session && <LiveNotes key={'notes-' + session.id} sessionId={session.id} />}
    <section aria-label="생성된 슬라이드"><h2>시각 슬라이드</h2><p>NOT_IMPLEMENTED · 생성된 슬라이드가 없습니다.</p></section>
  </main>;
}
