import fs from 'node:fs';
import path from 'node:path';
import puppeteer from 'puppeteer-core';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ROOT, discoverChrome } from '../e2e/core.mjs';
import { slideContent } from '../frontend/lib/slides.ts';

const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const h = React.createElement;
const katexDir = path.join(ROOT, 'node_modules/katex/dist');
const css = fs.readFileSync(path.join(katexDir, 'katex.min.css'), 'utf8').replace(/url\((fonts\/[^)]+)\)/g, (_, filename) => {
  const extension = path.extname(filename).slice(1);
  return `url(data:font/${extension};base64,${fs.readFileSync(path.join(katexDir, filename)).toString('base64')})`;
});
const html = '<!doctype html>' + renderToStaticMarkup(h('html', { lang: 'ko' },
  h('head', null, h('meta', { charSet: 'utf-8' }), h('style', null, css + '\n@page{size:A4 landscape;margin:14mm}body{font:15px Arial,"Malgun Gothic",sans-serif;color:#17202a}article{break-after:page}article:last-child{break-after:auto}h1{font-size:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #bbc7da;padding:10px;text-align:left}tr{break-inside:avoid}svg{max-height:450px}.no-print,.challenge-solution:not([open]){display:none}.sources{font-size:10px;color:#43506a;margin-top:16px}p{line-height:1.5}')),
  h('body', null, ...payload.slides.map(slide => h('article', { key: slide.id }, h('h1', null, slide.title), slideContent(slide, payload.includeAnswers),
    h('div', { className: 'sources' }, ...slide.evidenceRefs.map(id => {
      const item = payload.evidenceBundle?.questions.find(item => item.evidenceId === id);
      return h('p', { key: id }, `학습 증거 ${id}: ${item?.lectureTitle ?? ''} · ${item?.questionText ?? ''}`);
    }), ...slide.sourceRefs.map((ref, index) => h('p', { key: index }, `${ref.sourceType === 'material' ? `자료 ${ref.pageNumber}페이지` : '전사'} · ${ref.sourceId} · r${ref.revision}: ${ref.excerpt}`))))))));
let browser;
try {
  browser = await puppeteer.launch({ executablePath: discoverChrome(), headless: true, handleSIGINT: false, handleSIGTERM: false });
  const page = await browser.newPage();
  await page.setRequestInterception(true);
  page.on('request', request => ['data:', 'about:'].some(prefix => request.url().startsWith(prefix)) ? request.continue() : request.abort());
  await page.setContent(html, { waitUntil: 'load' }); await page.evaluate(() => document.fonts.ready);
  const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true });
  process.stdout.write(Buffer.from(pdf));
} finally { if (browser) await browser.close(); }
