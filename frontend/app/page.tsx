'use client';

import { useEffect, useState } from 'react';
import { BackendStatus } from '../components/backend-status';

export default function Page() {
  const [session, setSession] = useState('');
  useEffect(() => {
    setSession(new URL(window.location.href).searchParams.get('session') ?? '');
  }, []);

  return <main data-testid="lecture-app">
    <h1>강의 워크스페이스</h1>
    <BackendStatus />
    <p>웹앱 기능을 연결하기 위한 초기 화면입니다. 전사와 슬라이드는 아직 구현되지 않았습니다.</p>
    <p data-testid="session-state" data-session-id={session} data-state="idle">
      세션 상태: 대기
    </p>
    <section>
      <h2>강의자료</h2>
      <label>PDF 선택 <input data-testid="lecture-pdf-input" type="file" accept="application/pdf" disabled /></label>
      <button data-testid="lecture-upload" disabled>자료 업로드 · NOT_IMPLEMENTED</button>
    </section>
    <section>
      <h2>녹음</h2>
      <button data-testid="recording-start" disabled>녹음 시작 · NOT_IMPLEMENTED</button>
      <button data-testid="recording-stop" disabled>녹음 중지 · NOT_IMPLEMENTED</button>
      <button data-testid="session-end" disabled>세션 종료 · NOT_IMPLEMENTED</button>
    </section>
    <section aria-label="실시간 전사"><h2>자막</h2><p>NOT_IMPLEMENTED · 수신한 전사가 없습니다.</p></section>
    <section aria-label="생성된 슬라이드"><h2>시각 슬라이드</h2><p>NOT_IMPLEMENTED · 생성된 슬라이드가 없습니다.</p></section>
  </main>;
}
