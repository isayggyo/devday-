import React from 'react';
import { visualBody, type Visual } from './visual.ts';
export type FinalSlide = Visual & { kind: 'lecture' | 'challenge'; body: string; evidenceRefs: string[]; hints?: string[]; answer?: string; solution?: string; mathVerification?: string };
const h = React.createElement;

export function slideContent(slide: FinalSlide, printSolutions = false): React.ReactElement {
  const normalize = (text: string) => text.replace(/\s+/g, ' ').trim();
  const repeatedText = slide.layoutType === 'text_explanation' && normalize(slide.body) === normalize(slide.elements.paragraphs.join('\n'));
  return h('div', null, h('p', { style: { whiteSpace: 'pre-wrap' }, 'data-testid': 'slide-content' }, slide.body), repeatedText ? null : visualBody(slide),
    slide.kind === 'challenge' ? h('div', { 'data-testid': 'application-challenge' },
      h('details', { className: 'challenge-solution', open: printSolutions }, h('summary', null, '단계별 힌트'), h('ol', null, ...(slide.hints ?? []).map((hint, index) => h('li', { key: index }, hint)))),
      h('details', { className: 'challenge-solution', open: printSolutions }, h('summary', null, '정답과 풀이'), h('p', { style: { whiteSpace: 'pre-wrap' } }, slide.answer), h('p', { style: { whiteSpace: 'pre-wrap' } }, slide.solution)),
      h('p', { className: 'no-print' }, slide.mathVerification === 'verified' ? '제공된 수치 계산 확인됨 (풀이 전체의 검증은 아닙니다)' : '개념 풀이를 확인하세요. 수학적 증명 전체는 자동 검증하지 않았습니다.')) : null);
}
