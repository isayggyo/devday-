import React from 'react';
import katex from 'katex';

export type Layout = 'equation' | 'comparison' | 'flowchart' | 'concept_diagram' | 'text_explanation';
export type Visual = { id: string; answerId: string; layoutType: Layout | null; title: string; revision: number; status: string; errorCode: string | null;
  elements: { headings: string[]; rows: { label: string; values: string[] }[]; nodes: { id: string; label: string; detail: string }[]; edges: { fromId: string; toId: string; label: string }[]; equations: { latex: string; explanation: string }[]; paragraphs: string[] };
  sourceRefs: { sourceType: string; sourceId: string; revision: number; pageNumber: number | null; excerpt: string }[] };
const h = React.createElement;

export function mathMarkup(latex: string): { html: string | null; error: string | null } {
  try { return { html: katex.renderToString(latex, { displayMode: true, throwOnError: true, strict: 'error', trust: false, maxExpand: 500, maxSize: 10, macros: {} }), error: null }; }
  catch { return { html: null, error: '수식을 표시하지 못했습니다. 텍스트 설명을 참고해 주세요.' }; }
}

export function visualBody(visual: Visual): React.ReactElement {
  try {
    const { elements: e, layoutType: layout } = visual;
    if (layout === 'comparison') {
      if (e.headings.length < 2 || !e.rows.length || e.rows.some(row => row.values.length !== e.headings.length)) throw new Error('invalid comparison');
      return h('div', { style: { overflowX: 'auto' } }, h('table', { 'data-testid': 'visual-comparison' },
        h('thead', null, h('tr', null, h('th', { scope: 'col' }, '비교 기준'), ...e.headings.map((heading, index) => h('th', { key: index, scope: 'col' }, heading)))),
        h('tbody', null, ...e.rows.map((row, index) => h('tr', { key: index }, h('th', { scope: 'row' }, row.label), ...row.values.map((value, index) => h('td', { key: index }, value)))))));
    }
    if (layout === 'equation') {
      if (!e.equations.length) throw new Error('missing formula');
      return h('div', { 'data-testid': 'visual-equation' }, ...e.equations.map((equation, index) => {
        const math = mathMarkup(equation.latex);
        return h('div', { key: index }, math.html ? h('div', { dangerouslySetInnerHTML: { __html: math.html } }) : h('p', { role: 'status', 'data-testid': 'visual-fallback' }, math.error), h('p', null, equation.explanation));
      }));
    }
    if (layout === 'flowchart' || layout === 'concept_diagram') {
      const identifiers = new Set(e.nodes.map(node => node.id));
      if (e.nodes.length < 2 || e.nodes.length > 6 || identifiers.size !== e.nodes.length || !e.edges.length || e.edges.some(edge => !identifiers.has(edge.fromId) || !identifiers.has(edge.toId))) throw new Error('invalid diagram');
      const columns = layout === 'flowchart' ? 1 : 2, width = columns === 1 ? 540 : 760;
      const positions = new Map(e.nodes.map((node, index) => [node.id, { x: columns === 1 ? 270 : 190 + index % 2 * 380, y: 90 + Math.floor(index / columns) * 220 }]));
      const height = Math.ceil(e.nodes.length / columns) * 220;
      const marker = 'arrow-' + visual.id.replace(/[^A-Za-z0-9_-]/g, '');
      const edgeElements = e.edges.flatMap((edge, index) => {
        const a = positions.get(edge.fromId)!, b = positions.get(edge.toId)!;
        const dx = b.x-a.x, dy=b.y-a.y, length=Math.sqrt(dx*dx+dy*dy);
        if (!length) throw new Error('self edge');
        const distance = (x: number, y: number) => Math.min(x ? 145/Math.abs(x/length) : Infinity, y ? 70/Math.abs(y/length) : Infinity);
        const offset = distance(dx, dy) + 8;
        return [h('line', { key: `line-${index}`, x1: a.x+dx/length*offset, y1: a.y+dy/length*offset, x2: b.x-dx/length*offset, y2: b.y-dy/length*offset, stroke: '#788bb3', strokeWidth: 2, markerEnd: `url(#${marker})` }),
          h('text', { key: `label-${index}`, x: (a.x+b.x)/2, y: (a.y+b.y)/2-8, textAnchor: 'middle', fill: '#243352', fontSize: 13 }, edge.label.length > (columns === 2 ? 6 : 18) ? edge.label.slice(0, columns === 2 ? 5 : 17) + '…' : edge.label, h('title', null, edge.label))];
      });
      return h('div', null, h('svg', { 'data-testid': 'visual-diagram', viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': visual.title, style: { width: '100%', maxWidth: width } },
        h('title', null, visual.title), h('defs', null, h('marker', { id: marker, markerWidth: 10, markerHeight: 10, refX: 8, refY: 3, orient: 'auto', markerUnits: 'strokeWidth' }, h('path', { d: 'M0,0 L0,6 L9,3 z', fill: '#788bb3' }))), ...edgeElements,
        ...e.nodes.map(node => { const p = positions.get(node.id)!; return h('g', { key: node.id }, h('rect', { x: p.x-145, y: p.y-70, width: 290, height: 140, rx: 12, fill: '#eef3ff', stroke: '#8397c5' }),
          h('foreignObject', { x: p.x-133, y: p.y-60, width: 266, height: 120 }, h('div', { style: { textAlign: 'center', color: '#18243d', fontSize: 14, lineHeight: 1.25, overflowWrap: 'anywhere' } }, h('strong', null, node.label), h('p', { style: { margin: '6px 0' } }, node.detail)))); })),
        h('details', null, h('summary', null, '관계의 텍스트 설명'), ...e.edges.map((edge, index) => h('p', { key: index }, `${e.nodes.find(node => node.id === edge.fromId)?.label} → ${e.nodes.find(node => node.id === edge.toId)?.label}: ${edge.label}`))));
    }
    if (layout === 'text_explanation' && e.paragraphs.length) return h('div', { 'data-testid': 'visual-text' }, ...e.paragraphs.map((paragraph, index) => h('p', { key: index }, paragraph)));
    throw new Error('unknown layout');
  } catch { return h('p', { 'data-testid': 'visual-fallback', role: 'status' }, '시각 설명의 형식을 읽지 못했습니다. 위의 텍스트 답변을 참고해 주세요.'); }
}
