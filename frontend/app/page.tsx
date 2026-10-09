'use client';

import { useCallback, useState } from 'react';
import { BackendStatus } from '../components/backend-status';
import { SessionManager, type LectureSession } from '../components/session-manager';
import { Materials } from '../components/materials';
import { AudioRecorder } from '../components/audio-recorder';

export default function Page() {
  const [session, setSession] = useState<LectureSession | null>(null);
  const selectSession = useCallback((item: LectureSession) => setSession(item), []);
  const prepared = useCallback((sessionId: string) => setSession(previous => previous?.id === sessionId ? { ...previous, status: 'preparing' } : previous), []);

  return <main data-testid="lecture-app">
    <h1>강의 워크스페이스</h1>
    <BackendStatus />
    <p>웹앱 기능을 연결하기 위한 초기 화면입니다. 전사와 슬라이드는 아직 구현되지 않았습니다.</p>
    <SessionManager onSelect={selectSession} selected={session} />
    <Materials key={'materials-' + (session?.id ?? 'none')} session={session} onPrepared={prepared} />
    <AudioRecorder key={'audio-' + (session?.id ?? 'none')} session={session} onSession={selectSession} />
    <section aria-label="생성된 슬라이드"><h2>시각 슬라이드</h2><p>NOT_IMPLEMENTED · 생성된 슬라이드가 없습니다.</p></section>
  </main>;
}
