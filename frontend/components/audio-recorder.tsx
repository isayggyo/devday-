'use client';

import { useEffect, useRef, useState } from 'react';
import { AudioController, microphoneMessage, type CaptureUpdate } from '../lib/audio-controller';
import type { LectureSession } from './session-manager';
import { TranscriptionController, type TranscriptionUpdate } from '../lib/transcription';

export function AudioRecorder({ session, onSession }: { session: LectureSession | null; onSession: (session: LectureSession) => void }) {
  const controller = useRef<AudioController | null>(null);
  const transcription = useRef<TranscriptionController | null>(null);
  const enabled = useRef(true);
  const [transcribe, setTranscribe] = useState(true);
  const [captions, setCaptions] = useState<TranscriptionUpdate>({ status: 'idle', message: '', partial: '', segments: [] });
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState('');
  const [notice, setNotice] = useState('');
  const [capture, setCapture] = useState<CaptureUpdate>({ state: 'idle', pending: 0, bytes: 0, message: '' });

  useEffect(() => {
    if (!session) return;
    const instance = new AudioController(session, setCapture, onSession);
    controller.current = instance;
    const stt = new TranscriptionController(session.id, setCaptions);
    transcription.current = stt;
    void stt.load().catch(error => setNotice(microphoneMessage(error)));
    instance.onStream = stream => {
      if (stream && enabled.current) void stt.start(stream, instance.started).catch(error => setNotice(microphoneMessage(error)));
      if (!stream && stt.context) return stt.finish();
    };
    void instance.refresh().catch(error => setNotice(microphoneMessage(error)));
    const online = () => { void instance.retry(); };
    const visibility = () => {
      if (instance.state === 'recording') {
        instance.message = document.hidden ? '화면이 숨겨졌습니다. 돌아온 뒤 녹음 상태를 확인해 주세요.' : '화면으로 돌아왔습니다. 마이크 입력과 녹음 상태를 확인해 주세요.';
        void instance.report();
      }
    };
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (instance.state === 'recording' || instance.state === 'stopping') { event.preventDefault(); event.returnValue = ''; }
    };
    const pageHide = () => { if (instance.stream) void instance.stop(true); };
    window.addEventListener('online', online); window.addEventListener('beforeunload', beforeUnload); window.addEventListener('pagehide', pageHide); document.addEventListener('visibilitychange', visibility);
    return () => {
      instance.dispose(); controller.current = null;
      window.removeEventListener('online', online); window.removeEventListener('beforeunload', beforeUnload); window.removeEventListener('pagehide', pageHide); document.removeEventListener('visibilitychange', visibility);
    };
    // The keyed component owns one session; changes to its status keep the active recorder alive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.id, onSession]);

  useEffect(() => { if (controller.current && session) controller.current.session = session; }, [session]);

  async function selectDevices() {
    setNotice('');
    let preview: MediaStream | null = null;
    try {
      preview = await navigator.mediaDevices.getUserMedia({ audio: true });
      setDevices((await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'audioinput'));
    } catch (error) { setNotice(microphoneMessage(error)); }
    finally { preview?.getTracks().forEach(track => track.stop()); }
  }

  const active = ['recording', 'requesting', 'stopping'].includes(capture.state);
  return <><section aria-label="녹음">
    <h2>녹음</h2>
    <button disabled={!session || active} onClick={() => void selectDevices()}>마이크 권한 확인·장치 찾기</button>
    <label>입력 장치 <select aria-label="입력 장치" value={deviceId} disabled={active} onChange={event => setDeviceId(event.target.value)}><option value="">기본 마이크</option>{devices.map((device, index) => <option key={device.deviceId || index} value={device.deviceId}>{device.label || `마이크 ${index + 1}`}</option>)}</select></label>
    <label><input data-testid="transcription-enabled" type="checkbox" checked={transcribe} disabled={active} onChange={event => { enabled.current = event.target.checked; setTranscribe(event.target.checked); }} />실시간 전사 사용</label>
    <div>
      <button data-testid="recording-start" disabled={!session || active || !['created', 'preparing'].includes(session.status)} onClick={() => { setNotice(''); void controller.current?.start(deviceId).catch(error => setNotice(microphoneMessage(error))); }}>녹음 시작</button>
      <button data-testid="recording-stop" disabled={!session || capture.state === 'stopping' || !['recording', 'interrupted'].includes(capture.state)} onClick={() => { void controller.current?.stop().catch(error => setNotice(microphoneMessage(error))); }}>녹음 중지</button>
      <button data-testid="audio-retry" disabled={!capture.pending || capture.state === 'requesting'} onClick={() => void controller.current?.retry()}>미전송 청크 재전송</button>
      <button disabled={!capture.bytes} onClick={() => { void controller.current?.download().catch(error => setNotice(microphoneMessage(error))); }}>로컬 원본 내려받기</button>
    </div>
    <p data-testid="recording-state" data-state={capture.state}>{capture.state === 'recording' ? '녹음 중' : capture.state === 'requesting' ? '마이크 준비 중' : capture.state === 'stopping' ? '마지막 음성 청크 저장 중' : capture.state === 'stopped' ? '녹음 중지됨' : capture.state === 'interrupted' ? '녹음 중단 감지' : '녹음 대기'}</p>
    <p data-testid="audio-backup" data-pending={capture.pending} data-bytes={capture.bytes}>로컬 음성 {capture.bytes.toLocaleString()}바이트 · 전송 대기 {capture.pending}개</p>
    {(notice || capture.message) && <p role="status">{notice || capture.message}</p>}
    {session?.status === 'finalizing' && <p>원본 녹음이 저장됐습니다. 전사 확정 및 강의 종료 기능은 다음 단계에서 연결합니다.</p>}
    <button data-testid="session-end" disabled>세션 종료 · NOT_IMPLEMENTED</button>
  </section><section aria-label="실시간 전사"><h2>자막</h2>
    <p data-testid="transcription-status" data-status={captions.status}>{captions.status === 'connected' ? '전사 연결됨' : captions.status === 'connecting' ? '전사 연결 중' : captions.status === 'reconnecting' ? '전사 재연결 중 · 원본 녹음 유지' : captions.status === 'finalized' ? '전사 확정 완료' : captions.status === 'error' ? '전사 연결 실패 · 원본 녹음 유지' : '확정 자막을 기다리고 있습니다.'}</p>
    {captions.message && <p role="status">{captions.message}</p>}
    {active && <button data-testid="transcription-retry" onClick={() => transcription.current?.retry()}>전사 다시 연결</button>}
    {captions.partial && <p data-testid="transcript-partial">{captions.partial} <small>부분 전사 · 아직 확정되지 않음</small></p>}
    <ol>{captions.segments.map(segment => <li key={segment.id} data-testid="transcript-item" data-segment-id={segment.id}><time>{Math.floor(segment.startMs / 1000)}초</time> {segment.text}</li>)}</ol>
  </section></>;
}
