#!/usr/bin/env node
// Core-logic tests for 术语标注助手 v3.0 (extracts /*CORE*/ block from the HTML, no browser needed).

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, '..', '术语标注助手_v3.0.html'), 'utf-8');
const core = html.match(/\/\*CORE-START\*\/([\s\S]*?)\/\*CORE-END\*\//)[1];
const mod = new Function(core + `
  return { escapeHtml, buildAC, pickNonOverlap, computeWindow, matchesFilters, mergeImportedTerm, mapTemplateHeaders };
`)();

const results = [];
const check = (name, ok) => { results.push(ok); console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}`); };

// escapeHtml
check('escapeHtml', mod.escapeHtml('<a b="c">&') === '&lt;a b=&quot;c&quot;&gt;&amp;');

// AC automaton: matches + leftmost-longest
{
  const ac = mod.buildAC(['墨门', '墨门弟子', '八荒剑诀', '青长老']);
  const text = '青长老说墨门弟子需恪守门规，墨门后山藏有八荒剑诀。';
  const { matches, chars } = ac.search(text);
  const picked = mod.pickNonOverlap(matches).map(m => chars.slice(m.start, m.end).join(''));
  check('AC finds all occurrences', matches.length >= 4);
  check('leftmost-longest prefers 墨门弟子 over 墨门', picked.includes('墨门弟子'));
  check('standalone 墨门 still matched later', picked.includes('墨门'));
  check('picked order/content', JSON.stringify(picked) === JSON.stringify(['青长老', '墨门弟子', '墨门', '八荒剑诀']));
  check('empty AC returns null', mod.buildAC([]) === null);
  const ac2 = mod.buildAC(['abc']);
  check('no match on unrelated text', ac2.search('xyz').matches.length === 0);
}

// AC scale smoke: 30k terms, 200-char text
{
  const words = Array.from({ length: 30000 }, (_, i) => '词' + i.toString(36) + '条' + (i % 97));
  const t0 = Date.now();
  const ac = mod.buildAC(words);
  const buildMs = Date.now() - t0;
  const text = ('随机正文' + words[12345] + '夹杂' + words[29999]).repeat(3);
  const t1 = Date.now();
  for (let i = 0; i < 50; i++) ac.search(text);
  const scanMs = Date.now() - t1;
  check(`30k-term build <3s (${buildMs}ms) + 50-row scan <200ms (${scanMs}ms)`, buildMs < 3000 && scanMs < 200);
}

// computeWindow
{
  const w = mod.computeWindow(8400, 700, 100000, 84, 8);
  check('window start has buffer', w.start === 100 - 8);
  check('window end covers view+buffer', w.end === Math.ceil((8400 + 700) / 84) + 8);
  const w2 = mod.computeWindow(0, 700, 5, 84, 8);
  check('window clamps to total', w2.start === 0 && w2.end === 5);
  check('empty total', mod.computeWindow(0, 700, 0, 84, 8).end === 0);
}

// matchesFilters
{
  const row = ['K1', '青长老说墨门', ''];
  check('contains', mod.matchesFilters(row, { 1: { type: 'contains', value: '墨门' } }));
  check('not_contains', !mod.matchesFilters(row, { 1: { type: 'not_contains', value: '墨门' } }));
  check('equals', mod.matchesFilters(row, { 0: { type: 'equals', value: 'K1' } }));
  check('empty', mod.matchesFilters(row, { 2: { type: 'empty', value: '' } }));
  check('not_empty', !mod.matchesFilters(row, { 2: { type: 'not_empty', value: '' } }));
}

// mergeImportedTerm
{
  const ex = { category: '人名', translation: '', note: 'n', sourceKey: '', sourceText: 's', reviewStatus: 'approved', lastModified: 'T1', order: 7 };
  const inc = { category: '门派', translation: 'Momen', note: '', sourceKey: 'K9', sourceText: 'x', reviewStatus: 'pending', lastModified: 'T2', order: 99 };
  check('add when no existing', mod.mergeImportedTerm(null, inc, 'skip').action === 'add');
  check('skip keeps existing', mod.mergeImportedTerm(ex, inc, 'skip').action === 'skip');
  const ow = mod.mergeImportedTerm(ex, inc, 'overwrite');
  check('overwrite replaces but keeps order', ow.action === 'update' && ow.value.translation === 'Momen' && ow.value.order === 7);
  const fill = mod.mergeImportedTerm(ex, inc, 'fill');
  check('fill only blanks', fill.action === 'update' && fill.value.translation === 'Momen' && fill.value.sourceKey === 'K9'
    && fill.value.category === '人名' && fill.value.note === 'n' && fill.value.reviewStatus === 'approved');
}

// mapTemplateHeaders
{
  const m = mod.mapTemplateHeaders(['Key值', '术语分类', '术语原文', '术语译文', '备注', '来源原文', '审核状态', '最新修订时间']);
  check('8-col template maps exactly', m.key === 0 && m.category === 1 && m.term === 2 && m.translation === 3
    && m.note === 4 && m.source === 5 && m.status === 6 && m.time === 7);
  const m2 = mod.mapTemplateHeaders(['ukey', '分类', '术语原文', '译文']);
  check('aliases accepted (ukey/分类/译文)', m2.key === 0 && m2.category === 1 && m2.term === 2 && m2.translation === 3);
  check('missing 术语原文 -> -1', mod.mapTemplateHeaders(['a', 'b']).term === -1);
}

const n = results.filter(Boolean).length;
console.log(`\n${n}/${results.length} passed`);
process.exit(n === results.length ? 0 : 1);
