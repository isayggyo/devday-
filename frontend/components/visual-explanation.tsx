'use client';
import { useState } from 'react';
import { readJson } from '../lib/api';
import { visualBody, type Visual, type Layout } from '../lib/visual';

export function VisualExplanation({ sessionId, questionId, visual }: { sessionId: string; questionId: string; visual: Visual | null }) {
  const [layout, setLayout] = useState<Layout>('comparison'), [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function request() {
    setBusy(true); setError('');
    try { await readJson(await fetch(`/api/sessions/${sessionId}/questions/${questionId}/visual`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ preferredLayout: layout }) })); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '시각 설명 요청에 실패했습니다. 텍스트 답변을 참고해 주세요.'); }
    finally { setBusy(false); }
  }
  const running = busy || visual?.status === 'queued' || visual?.status === 'running';
  return <aside aria-label="답변 시각 설명">
    <label>시각 설명 형식 <select data-testid="visual-layout" value={layout} disabled={running} onChange={event => setLayout(event.target.value as Layout)}>
      <option value="comparison">비교표</option><option value="flowchart">흐름도</option><option value="concept_diagram">개념도</option><option value="equation">수식</option><option value="text_explanation">텍스트 설명</option>
    </select></label><button data-testid="visual-request" disabled={running} onClick={() => void request()}>{running ? '시각 설명 생성 중…' : visual?.status === 'failed' ? '시각 설명 다시 요청' : '시각 설명 요청'}</button>
    {error && <p role="status">{error}</p>}
    {visual?.status === 'failed' && <p role="status" data-testid="visual-fallback">시각 설명을 생성하지 못했습니다. 텍스트 답변은 유지됩니다. ({visual.errorCode})</p>}
    {visual && visual.revision > 0 && <figure data-testid="visual-explanation" data-status={visual.status} data-layout={visual.layoutType} data-revision={visual.revision}>
      <figcaption>{visual.title} · 버전 {visual.revision}</figcaption>{visualBody(visual)}
      <details><summary>시각 설명 근거</summary>{visual.sourceRefs.map((ref, index) => <blockquote key={index} data-testid="visual-source" data-source-id={ref.sourceId}><p>{ref.excerpt}</p><p>{ref.sourceType === 'material' ? `자료 ${ref.pageNumber}페이지` : '확정 전사'} · 버전 {ref.revision}</p></blockquote>)}</details>
    </figure>}
  </aside>;
}
