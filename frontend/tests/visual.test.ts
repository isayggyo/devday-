import assert from 'node:assert/strict';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { mathMarkup, visualBody, type Visual } from '../lib/visual.ts';

const elements = () => ({ headings: [], rows: [], nodes: [], edges: [], equations: [], paragraphs: [] });
function visual(layout: Visual['layoutType'], content: Partial<Visual['elements']>): Visual {
  return { id: 'unit-visual', answerId: 'unit-answer', layoutType: layout, title: 'Unit visual', revision: 1, status: 'ready', errorCode: null, elements: { ...elements(), ...content }, sourceRefs: [] };
}

test('KaTeX renders supported equations and preserves text for invalid equations', () => {
  assert.match(mathMarkup('E=mc^2').html ?? '', /katex/);
  assert.equal(mathMarkup('\\frac{').html, null);
  const html = renderToStaticMarkup(visualBody(visual('equation', { equations: [{ latex: '\\invalidcommand', explanation: 'Unit original explanation' }] })));
  assert.match(html, /visual-fallback/); assert.match(html, /Unit original explanation/);
  assert.doesNotMatch(mathMarkup('\\href{javascript:alert(1)}{x}').html ?? '', /href="javascript:/);
});

test('comparison and both diagram layouts render actual React table/SVG safely', () => {
  const table = renderToStaticMarkup(visualBody(visual('comparison', { headings: ['A', 'B'], rows: [{ label: 'Method', values: ['Recall', 'Space'] }] })));
  assert.match(table, /<table/); assert.match(table, /<td>Recall/);
  for (const layout of ['flowchart', 'concept_diagram'] as const) {
    const diagram = renderToStaticMarkup(visualBody(visual(layout, { nodes: [{ id: 'a', label: '<script>alert(1)</script>', detail: '' }, { id: 'b', label: 'Recall', detail: 'Unit evidence' }], edges: [{ fromId: 'a', toId: 'b', label: 'supports' }] })));
    assert.match(diagram, /<svg/); assert.match(diagram, /marker-end/); assert.doesNotMatch(diagram, /<script>/);
  }
});

test('malformed JSON data/layout content falls back and text layout remains available', () => {
  assert.match(renderToStaticMarkup(visualBody({ elements: null } as unknown as Visual)), /visual-fallback/);
  assert.match(renderToStaticMarkup(visualBody(visual('concept_diagram', { nodes: [{ id: 'a', label: 'A', detail: '' }], edges: [{ fromId: 'a', toId: 'missing', label: '' }] }))), /visual-fallback/);
  assert.match(renderToStaticMarkup(visualBody(visual('text_explanation', { paragraphs: ['Unit text explanation'] }))), /Unit text explanation/);
});
