'use client';

import { useEffect, useState } from 'react';
import { readJson, type BackendHealth } from '../lib/api';

export function BackendStatus() {
  const [health, setHealth] = useState<BackendHealth>();
  const [error, setError] = useState('');
  useEffect(() => {
    let current = true;
    fetch('/api/backend-health').then(readJson<BackendHealth>).then(result => { if (current) setHealth(result); }).catch(() => { if (current) setError('서버 연결을 확인해 주세요.'); });
    return () => { current = false; };
  }, []);
  return <p data-testid="backend-status" data-status={health?.database === 'ok' ? 'ok' : error ? 'error' : 'loading'}>
    {health ? <>서버 연결됨 · PostgreSQL 연결됨{health.auth_mode === 'development' && ' · 개발용 인증'}</> : error || '서버 연결 확인 중…'}
  </p>;
}
