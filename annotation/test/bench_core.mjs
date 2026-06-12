#!/usr/bin/env node
// Performance benchmark at target scale: 100k source rows x 30k terms.
// Measures the compute side of every hot path (DOM paint not covered; V8 == Chrome engine).

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, '..', '术语标注助手_v3.0.html'), 'utf-8');
const core = html.match(/\/\*CORE-START\*\/([\s\S]*?)\/\*CORE-END\*\//)[1];
const { escapeHtml, buildAC, pickNonOverlap, matchesFilters } = new Function(core + `
  return { escapeHtml, buildAC, pickNonOverlap, matchesFilters };
`)();

const HANZI = '的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六共权收证改清美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严龙飞';
const rnd = n => Math.floor(Math.random() * n);
const word = len => { let s = ''; for (let i = 0; i < len; i++) s += HANZI[rnd(HANZI.length)]; return s; };
const ms = t0 => (performance.now() - t0).toFixed(0) + 'ms';

const N_ROWS = 100000, N_TERMS = 30000;
console.log(`scale: ${N_ROWS} rows x ${N_TERMS} terms\n`);

// ── generate data ──
let t0 = performance.now();
const termSet = new Set();
while (termSet.size < N_TERMS) termSet.add(word(2 + rnd(5)));
const terms = [...termSet];
const rows = new Array(N_ROWS);
for (let i = 0; i < N_ROWS; i++) {
  let line = word(20 + rnd(40));
  const k = rnd(4);
  for (let j = 0; j < k; j++) { const p = rnd(line.length); line = line.slice(0, p) + terms[rnd(N_TERMS)] + line.slice(p); }
  rows[i] = ['KEY_' + i, line, ''];
}
console.log(`data generated            ${ms(t0)}`);

// ── 1. AC build (term-table change, debounced 300ms) ──
t0 = performance.now();
const ac = buildAC(terms);
console.log(`1. AC build 30k terms     ${ms(t0)}   (触发: 词表变更后防抖重建)`);

// ── 2. full inverted-index scan (import; chunked in app, total CPU here) ──
t0 = performance.now();
const termIndex = new Map();
for (let i = 0; i < N_ROWS; i++) {
  const { matches, chars } = ac.search(rows[i][1]);
  if (!matches.length) continue;
  const seen = new Set();
  for (const m of matches) {
    const t = chars.slice(m.start, m.end).join('');
    if (seen.has(t)) continue;
    seen.add(t);
    let a = termIndex.get(t); if (!a) { a = []; termIndex.set(t, a); }
    a.push(i);
  }
}
const idxMs = performance.now() - t0;
console.log(`2. index scan 100k rows   ${idxMs.toFixed(0)}ms  (触发: 导入后一次, 应用内分片后台跑, 验收<10s)`);

// ── 3. visible-window render compute: 50 rows highlight+escape ──
t0 = performance.now();
let html50 = '';
for (let r = 0; r < 50; r++) {
  const text = rows[rnd(N_ROWS)][1];
  const { matches, chars } = ac.search(text);
  const picked = pickNonOverlap(matches);
  let h = '', pos = 0;
  for (const m of picked) { h += escapeHtml(chars.slice(pos, m.start).join('')) + '<span>' + escapeHtml(chars.slice(m.start, m.end).join('')) + '</span>'; pos = m.end; }
  html50 += h + escapeHtml(chars.slice(pos).join(''));
}
console.log(`3. render window (50 rows) ${ms(t0)}   (触发: 每次滚动/变更, 验收<100ms)`);

// ── 4. filter pass over 100k rows (debounced 200ms per keystroke) ──
t0 = performance.now();
const filters = { 1: { type: 'contains', value: terms[0] } };
let vis = 0;
for (let i = 0; i < N_ROWS; i++) if (matchesFilters(rows[i], filters)) vis++;
console.log(`4. filter scan 100k rows  ${ms(t0)}   (触发: 筛选输入防抖后, 验收<200ms, 命中${vis}行)`);

// ── 5. incremental index for one new term ──
t0 = performance.now();
const newTerm = terms[123];
const ids = [];
for (let i = 0; i < N_ROWS; i++) if (rows[i][1].includes(newTerm)) ids.push(i);
console.log(`5. single-term index add  ${ms(t0)}   (触发: 手动加一个术语, 验收<100ms)`);

// ── 6. draft serialize: 30k terms ──
const details = terms.map(t => [t, { category: '分类', note: '', translation: 'Trans ' + t, sourceKey: 'K', sourceText: t, reviewStatus: 'pending', lastModified: '2026-06-12T00:00:00', order: 0 }]);
t0 = performance.now();
const draft = JSON.stringify({ termDetails: details });
console.log(`6. draft serialize 30k    ${ms(t0)}   (触发: 每60s, 体积${(draft.length / 1048576).toFixed(1)}MB, localStorage配额~5-10MB)`);

// ── 7. project JSON with full rows ──
t0 = performance.now();
const proj = JSON.stringify({ rows, termDetails: details });
console.log(`7. project save 100k rows ${ms(t0)}   (触发: 手动/定时备份, 体积${(proj.length / 1048576).toFixed(1)}MB)`);

const mem = process.memoryUsage();
console.log(`\nheap used: ${(mem.heapUsed / 1048576).toFixed(0)}MB (rows+index+AC in memory)`);
console.log('note: DOM 绘制开销不在本基准内（虚拟滚动恒定~50行, 绘制成本与数据量无关）');
