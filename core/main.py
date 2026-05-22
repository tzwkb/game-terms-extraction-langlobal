#!/usr/bin/env python3
import sys, os, time, signal, json, re, random
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from pathlib import Path
from typing import List, Dict, Tuple
import pandas as pd
import yaml
import jieba
from openai import AsyncOpenAI

_interrupted = False

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import EXTRACTOR_CONFIG, VOTE_TEMPS
from core.prompt_base import build_system_prompt, build_user_prompt, build_translation_prompt
from core.llm_extractor import LLMExtractor
from core.llm_translator import TermTranslator
from core.logger import setup_logging
from core.checkpoint import load as ckpt_load, save as ckpt_save, save_meta as ckpt_save_meta
from core.embed_store import EmbedStore
import logging
logger = logging.getLogger("pipeline")

_VAR_RE = re.compile(r'\$\{[^}]*\}|\$[a-zA-Z_]\w*|\$\d+')


def _on_interrupt(sig, frame):
    global _interrupted
    _interrupted = True
    logger.info("Interrupt received, finishing current batch...")


try:
    signal.signal(signal.SIGINT, _on_interrupt)
except ValueError:
    pass  # not in main thread (e.g. Streamlit background thread)


def load_config(profile_name: str = "yanyun") -> dict:
    with open(ROOT / "profiles" / f"{profile_name}.yaml", encoding="utf-8") as f:
        profile = yaml.safe_load(f)
    return profile


def load_glossary(path: str, cn_col: int = 0, en_col: int = 1) -> Tuple[dict, set]:
    df = pd.read_excel(path)
    glossary = {}
    keys = set()
    for _, row in df.iterrows():
        cn = str(row.iloc[cn_col]).strip()
        en = str(row.iloc[en_col]).strip()
        if cn and cn != "nan":
            glossary[cn.lower()] = (cn, en)
            keys.add(cn)
    return glossary, keys


def _batch_match_context(terms: List[dict], source_texts: List[str]) -> None:
    remaining = {t["term"] for t in terms}
    term_context: Dict[str, str] = {}
    for text in source_texts:
        found = [term for term in remaining if term in text]
        for term in found:
            term_context[term] = text.replace("\n", " ").strip()
            remaining.discard(term)
        if not remaining:
            break
    for t in terms:
        t["source_text"] = term_context.get(t["term"], "")


def _chunk_texts(texts: List[str], target_chars: int, overlap: int = 3) -> List[str]:
    chunks, cur, cur_c = [], [], 0
    for t in texts:
        if cur_c + len(t) > target_chars and cur:
            chunks.append("\n\n".join(cur))
            cur = cur[-overlap:]
            cur_c = sum(len(s) for s in cur) + (len(cur) - 1) * 2
        cur.append(t)
        cur_c += len(t)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def _run_batch_votes(extractor, batch_c, system, batch_p, model, max_tokens, concurrent, batch_f, batch_id, progress_callback=None):
    async def _gather():
        async def _one(vote_idx, temp):
            results = await extractor.run_batch_async(
                texts=batch_c, system_prompt=system, user_prompts=batch_p,
                model=model, temperature=temp, max_tokens=max_tokens,
                max_concurrent=concurrent, source_files=batch_f,
                batch_id=f'{batch_id}_v{vote_idx}',
                progress=lambda done, total: progress_callback and progress_callback(
                    "extracting", 0, 0, f"v{vote_idx+1}: {done}/{total} chunks")
            )
            results.sort(key=lambda x: x.get("custom_id", ""))
            return results
        return await asyncio.gather(*[_one(v, VOTE_TEMPS[v]) for v in range(3)])
    return asyncio.run(_gather())


NER_SYSTEM = """从游戏中文文本中提取命名实体。严格按 JSON 格式输出:
{"persons": ["人名1", ...], "places": ["地名1", ...]}

规则:
- persons: 所有中文人名，包括 "老X"、"小X"、"阿X"、"X嫂"、"X伯"、"X叔"、"X爷"、"X娘"、"X儿"、"X哥"、"X弟"、"X师傅" 等称呼形式。不确定的标为 persons。
- places: 所有地名、地点、场所、门派、组织。
- 只输出 JSON，不要任何额外文字。"""

NER_MODEL = "gemini-3.1-flash-lite"

def _rule_extract(batch_c, profile):
    rules = profile.get("rule_extractors")
    if not rules:
        return []
    results = []
    if "surname_names" in rules:
        cfg = rules["surname_names"]
        surnames = set(cfg["surnames"])
        mn, mx = cfg.get("min_len", 2), cfg.get("max_len", 3)
        for c in batch_c:
            for token in jieba.cut(c):
                if mn <= len(token) <= mx and token[0] in surnames:
                    results.append(token)
    return list(set(results))


async def _ner_flash_batch(batch_c, api_key, base_url):
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=1)
    sem = asyncio.Semaphore(5)
    results = {}

    async def _one(idx, text):
        async with sem:
            delay = 2.0
            for attempt in range(1, 8):
                try:
                    resp = await client.chat.completions.create(
                        model=NER_MODEL,
                        messages=[{"role": "system", "content": NER_SYSTEM}, {"role": "user", "content": text}],
                        temperature=0, max_tokens=2048,
                    )
                    raw = resp.choices[0].message.content.strip()
                    m = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n\s*```', raw)
                    if m:
                        raw = m.group(1).strip()
                    parsed = json.loads(raw)
                    results[idx] = (parsed.get("persons", []), parsed.get("places", []))
                    return
                except Exception:
                    if attempt < 7:
                        await asyncio.sleep(delay + random.uniform(0, delay * 0.5))
                        delay = min(delay * 2, 30)
            results[idx] = ([], [])

    tasks = [_one(i, c) for i, c in enumerate(batch_c) if c.strip()]
    for i, c in enumerate(batch_c):
        if not c.strip():
            results[i] = ([], [])
    await asyncio.gather(*tasks)

    all_persons, all_places = set(), set()
    for i in range(len(batch_c)):
        ps, pls = results.get(i, ([], []))
        all_persons.update(ps)
        all_places.update(pls)
    return list(all_persons), list(all_places)


def _ner_scan(batch_c, api_key, base_url):
    return asyncio.run(_ner_flash_batch(batch_c, api_key, base_url))


def _collect_llm_votes(raw_v_all):
    all_votes = []
    for v, raw_v in enumerate(raw_v_all):
        for r in raw_v:
            for t in r.get("extracted_terms", {}).get("terms", []):
                term = t.get("term", t.get("zh_term", "")).strip()
                if term:
                    all_votes.append({"term": term, "category": t.get("category", ""), "_vote": v})
    return all_votes


def _count_llm_votes(all_votes):
    term_counts, term_data = {}, {}
    for t in all_votes:
        k = t["term"].lower()
        term_counts[k] = term_counts.get(k, 0) + 1
        if k not in term_data:
            term_data[k] = t
    results = []
    for k, cnt in term_counts.items():
        if cnt >= 3:
            td = term_data[k]
            results.append({"term": td["term"], "category": td["category"]})
    return results


def _in_glossary(term: str, glossary_keys: set) -> bool:
    return bool(glossary_keys and term in glossary_keys)


def filter_derived_terms(terms: List[dict], address_suffixes: list, glossary_keys: set = None) -> List[dict]:
    """Remove NPC 称谓派生变体 (e.g. 冯大哥→冯) keeping the canonical form.
    Terms in glossary_keys are never filtered.
    """
    suffixes = sorted(address_suffixes, key=len, reverse=True)
    term_set = set(t["term"] for t in terms)
    result = []
    for t in terms:
        term = t["term"]
        if _in_glossary(term, glossary_keys):
            result.append(t)
            continue
        is_derivative = False
        for suffix in suffixes:
            if term.endswith(suffix) and len(term) > len(suffix):
                stem = term[:-len(suffix)]
                if stem in term_set or any(o != term and o.startswith(stem) for o in term_set):
                    is_derivative = True
                    break
        if not is_derivative:
            result.append(t)
    return result


def extract_terms(texts: List[str], profile: dict, api_key: str, base_url: str, model: str,
                  target_chars: int = 1200, max_tokens: int = None, concurrent: int = None,
                  output_dir: str = "", raw_dir: str = "", checkpoint_dir: str = "",
                  glossary_keys: set = None,
                  progress_callback: callable = None) -> List[dict]:
    if concurrent is None:
        concurrent = EXTRACTOR_CONFIG["max_concurrent"]
    if max_tokens is None:
        max_tokens = EXTRACTOR_CONFIG["max_tokens"]
    if not output_dir:
        output_dir = "output"
    t0 = time.time()
    chunks = _chunk_texts(texts, target_chars)

    start_idx = 0
    results = []
    if checkpoint_dir:
        ckpt = ckpt_load(checkpoint_dir)
        if ckpt["chunk_idx"] > 0:
            start_idx = ckpt["chunk_idx"]
            results = ckpt["terms"]
            logger.info(f"Checkpoint: resume from chunk {start_idx}/{len(chunks)}, {len(results)} terms")

    system = build_system_prompt(profile)
    extractor = LLMExtractor(api_key=api_key, base_url=base_url, base_dir=output_dir, cache_dir=checkpoint_dir)

    if raw_dir:
        os.makedirs(f"{raw_dir}/extraction", exist_ok=True)
        with open(f"{raw_dir}/extraction/system_prompt.txt", "w", encoding="utf-8") as f:
            f.write(system)

    for i in range(start_idx, len(chunks), concurrent):
        if _interrupted:
            logger.warning(f"Stopped at chunk {i}/{len(chunks)}")
            break

        end = min(i + concurrent, len(chunks))
        batch_c = chunks[i:end]
        if progress_callback:
            progress_callback("extracting", end, len(chunks),
                              f"NER 预扫描 chunk {i+1}-{end}…")
        ner_persons, ner_places = _ner_scan(batch_c, api_key, base_url)
        if progress_callback:
            progress_callback("extracting", end, len(chunks),
                              f"NER done, starting LLM votes for chunk {i+1}-{end}…")
        rule_persons = _rule_extract(batch_c, profile)
        all_persons = list(set(ner_persons + rule_persons))
        batch_p = [
            build_user_prompt(profile, c, include_context=False,
                              jieba_hints=list(set(jieba.cut(c)) & glossary_keys) if glossary_keys else None,
                              ner_hints={'persons': [p for p in all_persons if p in c],
                                         'places': [p for p in ner_places if p in c]})
            for c in batch_c
        ]

        t_batch = time.time()
        raw_v_all = _run_batch_votes(extractor, batch_c, system, batch_p, model, max_tokens, concurrent,
                                     [f"c{j}" for j in range(i, end)], f'b{i}',
                                     progress_callback=progress_callback)

        if raw_dir:
            for j, r in enumerate(raw_v_all[0]):
                with open(f"{raw_dir}/extraction/response_{i + j}.json", "w", encoding="utf-8") as f:
                    json.dump(r, f, ensure_ascii=False, indent=2, default=str)

        llm_votes = _collect_llm_votes(raw_v_all)
        batch_results = _count_llm_votes(llm_votes)
        results.extend(batch_results)

        dt = time.time() - t_batch
        pct = end / len(chunks) * 100
        elapsed = time.time() - t0
        etc = elapsed / end * (len(chunks) - end) if end else 0
        logger.info(f"[{end}/{len(chunks)}] {pct:.0f}% | +{len(batch_results)} terms, total:{len(results)} | {dt:.0f}s | elapsed:{elapsed/60:.1f}m, ETC:{etc/60:.0f}m")
        if progress_callback:
            progress_callback("extracting", end, len(chunks),
                              f"+{len(batch_results)} terms, {len(results)} total | {elapsed/60:.1f}m elapsed, ETC {etc/60:.0f}m")

        if checkpoint_dir and (end % (concurrent * 2) == 0 or end == len(chunks)):
            ckpt_save(checkpoint_dir, end, results, len(chunks))

    seen = {}
    for t in results:
        k = t["term"].lower()
        if k not in seen:
            seen[k] = t
    terms = list(seen.values())

    address_suffixes = profile.get("address_suffixes", [])
    before = len(terms)
    terms = filter_derived_terms(terms, address_suffixes, glossary_keys)
    if before != len(terms):
        logger.info(f"filter_derived_terms removed {before - len(terms)} NPC nickname variants ({before} → {len(terms)})")

    _batch_match_context(terms, texts)

    return terms


def match_and_translate(extracted: List[dict], glossary: dict, profile: dict,
                        api_key: str, base_url: str, model: str,
                        raw_dir: str = "", embed_store: EmbedStore = None) -> List[dict]:
    glossary_keys = list(glossary.keys())
    exact_matched = []
    need_translate = []

    for t in extracted:
        key = t["term"].lower()
        if key in glossary:
            exact_matched.append({**t, "translation": glossary[key][1], "match_type": "exact"})
        else:
            need_translate.append(t)

    logger.info(f"Exact: {len(exact_matched)} | Need LLM translate: {len(need_translate)}")

    if not need_translate:
        return exact_matched

    logger.info("Computing top-1 reference via embedding...")
    query_terms = [t["term"] for t in need_translate]
    refs = embed_store.search(query_terms) if embed_store else []

    for i, t in enumerate(need_translate):
        cn_ref, sim = refs[i]
        if cn_ref not in glossary:
            # stale DB entry for a term no longer in current glossary
            cn_ref = glossary_keys[0] if glossary_keys else ""
            sim = 0.0
        en_ref = glossary[cn_ref][1] if cn_ref else ""
        t["_ref_term"] = cn_ref
        t["_ref_trans"] = en_ref
        t["_ref_sim"] = sim

    sys_prompt, user_prompt = build_translation_prompt(profile, need_translate)
    translator = TermTranslator(api_key=api_key, base_url=base_url, model=model, profile=profile)
    t_trans = time.time()
    logger.info(f"Translating {len(need_translate)} terms via LLM...")
    trans_map = translator.translate_with_hints(sys_prompt, user_prompt)
    dt_trans = time.time() - t_trans
    logger.info(f"Translation done: {len(trans_map)}/{len(need_translate)} mapped | {dt_trans:.0f}s")

    if raw_dir:
        os.makedirs(f"{raw_dir}/translation", exist_ok=True)
        with open(f"{raw_dir}/translation/system_prompt.txt", "w", encoding="utf-8") as f:
            f.write(sys_prompt)
        with open(f"{raw_dir}/translation/user_prompt.txt", "w", encoding="utf-8") as f:
            f.write(user_prompt)
        with open(f"{raw_dir}/translation/response.json", "w", encoding="utf-8") as f:
            json.dump(list(trans_map.items()), f, ensure_ascii=False, indent=2)

    translated = []
    for t in need_translate:
        en = trans_map.get(t["term"], "")
        translated.append({**t, "translation": en, "match_type": "llm_translated",
                           "ref_term": t["_ref_term"], "ref_trans": t["_ref_trans"], "ref_sim": t["_ref_sim"]})

    return exact_matched + translated


def run_pipeline(source_path: str, glossary_path: str, profile_name: str = "yanyun",
                 api_key: str = "", base_url: str = "https://api.openai.com/v1",
                 model: str = "gemini-3.1-pro-preview",
                 output_dir: str = "", raw_dir: str = "", checkpoint_dir: str = "",
                 progress_callback: callable = None,
                 src_col: int = 0, gl_cn_col: int = 0, gl_en_col: int = 1,
                 embed_workers: int = 16) -> List[dict]:

    if not output_dir:
        output_dir = "output"
    setup_logging(log_dir=output_dir)
    if checkpoint_dir:
        ckpt_save_meta(checkpoint_dir, {
            "src_col": src_col, "gl_cn_col": gl_cn_col, "gl_en_col": gl_en_col,
            "src_filename": Path(source_path).name,
            "gl_filename": Path(glossary_path).name,
        })
    profile = load_config(profile_name)
    glossary, glossary_keys = load_glossary(glossary_path, cn_col=gl_cn_col, en_col=gl_en_col)
    for gk in glossary_keys:
        jieba.suggest_freq(gk, tune=True)

    db_path = ROOT / "database" / "glossary_embeddings.db"
    db_path.parent.mkdir(exist_ok=True)
    embed_store = EmbedStore(str(db_path), api_key, base_url)
    if progress_callback:
        progress_callback("loading", 0, 1, f"同步术语向量库 ({len(glossary_keys)} 条)…")
    added, removed = embed_store.sync(list(glossary_keys), progress=progress_callback, workers=embed_workers)
    logger.info(f"Embedding store synced: +{added} added, -{removed} removed, {embed_store.count} total")

    df_src = pd.read_excel(source_path)
    texts = df_src.iloc[:, src_col].dropna().astype(str).str.strip().tolist()
    texts = [t for t in texts if t]
    texts = list(dict.fromkeys(texts))
    texts = [_VAR_RE.sub('', t).strip() for t in texts]
    texts = [t for t in texts if t]
    logger.info(f"Source: {len(df_src)} rows -> {len(texts)} after dedup")
    if progress_callback:
        progress_callback("loading", 1, 1, f"{len(texts)} texts loaded, {len(glossary_keys)} glossary terms")
        progress_callback("extracting", 0, 1, "即将开始提取…")
    logger.info("Extracting terms...")
    extracted = extract_terms(texts, profile, api_key, base_url, model, output_dir=output_dir, raw_dir=raw_dir, checkpoint_dir=checkpoint_dir, glossary_keys=glossary_keys, progress_callback=progress_callback)

    filterable = set(profile.get("filterable_categories", []))
    if filterable:
        before = len(extracted)
        extracted = [t for t in extracted if t.get("category") not in filterable or _in_glossary(t["term"], glossary_keys)]
        if before != len(extracted):
            logger.info(f"category filter removed {before - len(extracted)} terms ({before} → {len(extracted)})")

    logger.info("Matching + translating via embedding...")
    if progress_callback:
        progress_callback("translating", 0, 1, f"Exact: {sum(1 for t in extracted if t['term'].lower() in glossary)} matched, translating rest...")
    results = match_and_translate(extracted, glossary, profile, api_key, base_url, model, raw_dir=raw_dir, embed_store=embed_store)
    if progress_callback:
        progress_callback("translating", 1, 1, f"{len(results)} terms translated")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="test_file/原文.xlsx")
    parser.add_argument("--glossary", default="test_file/【日更】0514术语表.xlsx")
    parser.add_argument("--profile", default="yanyun")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""))
    parser.add_argument("--base-url", default="https://api.vectorengine.ai/v1")
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    t0 = time.time()
    out_dir = args.output or f"output/run_{time.strftime('%Y%m%d_%H%M')}"
    raw_dir = f"{out_dir}/raw_data"

    results = run_pipeline(args.source, args.glossary, args.profile,
                           args.api_key, args.base_url, args.model,
                           raw_dir=raw_dir)

    os.makedirs(out_dir, exist_ok=True)
    pd.DataFrame(results).to_excel(f"{out_dir}/results.xlsx", index=False)
    print(f"\nDone. {len(results)} terms. Output: {out_dir}")
    print(f"Total: {(time.time()-t0)/60:.1f}m")
