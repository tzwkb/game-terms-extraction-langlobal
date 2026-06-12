#!/usr/bin/env node
// Stress test BEYOND acceptance targets: scale ramps + pathological inputs.
// Compute side only (V8); DOM paint is constant-window by design.

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, '术语标注助手_v3.0.html'), 'utf-8');
const core = html.match(/\/\*CORE-START\*\/([\s\S]*?)\/\*CORE-END\*\//)[1];
const { escapeHtml, buildAC, pickNonOverlap, matchesFilters } = new Function(core + `
  return { escapeHtml, buildAC, pickNonOverlap, matchesFilters };
`)();

const HANZI = '的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意';
const rnd = n => Math.floor(Math.random() * n);
const word = len => { let s = ''; for (let i = 0; i < len; i++) s += HANZI[rnd(HANZI.length)]; return s; };
const heap = () => (process.memoryUsage().heapUsed / 1048576).toFixed(0) + 'MB';
const T = () => performance.now();

function genTerms(n) { const s = new Set(); while (s.size < n) s.add(word(2 + rnd(5))); return [...s]; }
function genRows(n, terms) {
  const rows = new Array(n);
  for (let i = 0; i < n; i++) {
    let line = word(20 + rnd(40));
    for (let j = 0, k = rnd(4); j < k; j++) { const p = rnd(line.length); line = line.slice(0, p) + terms[rnd(terms.length)] + line.slice(p); }
    rows[i] = line;
  }
  return rows;
}
function indexScan(rows, ac) {
  const idx = new Map();
  for (let i = 0; i < rows.length; i++) {
    const { matches, chars } = ac.search(rows[i]);
    if (!matches.length) continue;
    const seen = new Set();
    for (const m of matches) {
      const t = chars.slice(m.start, m.end).join('');
      if (seen.has(t)) continue;
      seen.add(t);
      let a = idx.get(t); if (!a) { a = []; idx.set(t, a); }
      a.push(i);
    }
  }
  return idx;
}
function renderRow(text, ac) {
  const { matches, chars } = ac.search(text);
  const picked = pickNonOverlap(matches);
  let h = '', pos = 0;
  for (const m of picked) { h += escapeHtml(chars.slice(pos, m.start).join('')) + '<span>' + escapeHtml(chars.slice(m.start, m.end).join('')) + '</span>'; pos = m.end; }
  return h + escapeHtml(chars.slice(pos).join(''));
}

console.log('═══ A. 行数递增（固定 3 万词）═══');
{
  const terms = genTerms(30000);
  const ac = buildAC(terms);
  for (const n of [100000, 300000, 1000000]) {
    let t0 = T(); const rows = genRows(n, terms); const genMs = T() - t0;
    t0 = T(); indexScan(rows, ac); const idxMs = T() - t0;
    t0 = T(); const filters = { 0: { type: 'contains', value: terms[0] } };
    let vis = 0; for (let i = 0; i < n; i++) if (matchesFilters([rows[i]], filters)) vis++;
    const filtMs = T() - t0;
    console.log(`${(n / 10000).toFixed(0)}万行: 索引${idxMs.toFixed(0)}ms 筛选${filtMs.toFixed(0)}ms 堆${heap()} (生成${genMs.toFixed(0)}ms)`);
  }
}

console.log('\n═══ B. 词数递增（固定 10 万行）═══');
{
  for (const nt of [30000, 100000, 300000]) {
    const terms = genTerms(nt);
    let t0 = T(); const ac = buildAC(terms); const buildMs = T() - t0;
    const rows = genRows(100000, terms);
    t0 = T(); indexScan(rows, ac); const idxMs = T() - t0;
    t0 = T(); for (let i = 0; i < 50; i++) renderRow(rows[rnd(rows.length)], ac); const rdMs = T() - t0;
    console.log(`${(nt / 10000).toFixed(0)}万词: AC构建${buildMs.toFixed(0)}ms 索引${idxMs.toFixed(0)}ms 渲染50行${rdMs.toFixed(0)}ms 堆${heap()}`);
  }
}

console.log('\n═══ C. 病态输入 ═══');
{
  const terms = genTerms(30000);
  const ac = buildAC(terms);

  // C1: single huge cell (100k chars) — worst render path
  let huge = '';
  for (let i = 0; i < 1000; i++) huge += word(95) + terms[rnd(terms.length)];
  let t0 = T(); const { matches } = ac.search(huge); const searchMs = T() - t0;
  t0 = T(); const h = renderRow(huge, ac); const rdMs = T() - t0;
  console.log(`C1 超长单行(${huge.length}字): AC搜索${searchMs.toFixed(0)}ms 完整渲染${rdMs.toFixed(0)}ms HTML${(h.length / 1024).toFixed(0)}KB 命中${matches.length}处`);

  // C2: dense hits — line made of nothing but terms
  let dense = ''; for (let i = 0; i < 200; i++) dense += terms[rnd(terms.length)];
  t0 = T(); for (let i = 0; i < 50; i++) renderRow(dense, ac); const dMs = T() - t0;
  console.log(`C2 高密度行(全是术语,${dense.length}字)×50行渲染: ${dMs.toFixed(0)}ms`);

  // C3: single-char terms — match explosion
  const oneChar = [...new Set(Array.from({ length: 200 }, () => HANZI[rnd(HANZI.length)]))];
  const acOne = buildAC(oneChar);
  const line = word(60);
  t0 = T(); for (let i = 0; i < 50; i++) renderRow(line, acOne); const oMs = T() - t0;
  const m1 = acOne.search(line).matches.length;
  console.log(`C3 ${oneChar.length}个单字术语,60字行命中${m1}处,×50行渲染: ${oMs.toFixed(0)}ms`);

  // C4: nested families (墨/墨门/墨门弟/墨门弟子 x2000 families)
  const fam = [];
  for (let i = 0; i < 2000; i++) { const base = word(5); for (let l = 1; l <= 4; l++) fam.push(base.slice(0, l)); }
  t0 = T(); const acFam = buildAC([...new Set(fam)]); const fBuild = T() - t0;
  const ftext = Array.from({ length: 50 }, () => fam[rnd(fam.length)]).join('');
  t0 = T(); for (let i = 0; i < 50; i++) renderRow(ftext, acFam); const fMs = T() - t0;
  console.log(`C4 嵌套词族${new Set(fam).size}词: 构建${fBuild.toFixed(0)}ms ×50密集行渲染${fMs.toFixed(0)}ms`);

  // C5: edges
  const okEmpty = buildAC([]) === null && renderRow('', ac) === '' && pickNonOverlap([]).length === 0;
  const idx1 = indexScan(['只有一行的墨门测试'], buildAC(['墨门']));
  console.log(`C5 空词表/空行/单行边界: ${okEmpty && idx1.get('墨门')?.length === 1 ? 'OK' : 'FAIL'}`);

  // C6: draft size at 100k terms
  const big = genTerms(100000).map(t => [t, { category: '分类', note: '', translation: 'T' + t, sourceKey: 'K', sourceText: t, reviewStatus: 'pending', lastModified: '2026-06-12T00:00:00', order: 0 }]);
  t0 = T(); const js = JSON.stringify({ termDetails: big });
  console.log(`C6 10万词草稿: 序列化${(T() - t0).toFixed(0)}ms 体积${(js.length / 1048576).toFixed(1)}MB (localStorage配额5-10MB → 超限静默跳过)`);
}
console.log(`\nfinal heap: ${heap()}`);
