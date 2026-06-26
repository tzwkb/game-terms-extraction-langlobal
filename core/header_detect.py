#!/usr/bin/env python3
"""Auto-detect Excel column roles via LLM, backed by a persistent header dictionary.

Self-contained by design: the detection prompt lives in this single file and is not
surfaced in UI/config. Provide an OpenAI-compatible key via the DETECT_API_KEY env
var to enable column auto-detection; if unset, the app falls back to manual column
mapping.

Persistent header dictionary (`header_cache.json` at repo root): every header layout,
once identified — by the AI **or** by the user's manual column choice — is remembered.
The next identical header is served straight from the dictionary, skipping the LLM.
Human-confirmed mappings outrank later AI guesses.
"""

import os
import json
import re
from pathlib import Path
import pandas as pd
from openai import OpenAI

# Detection key comes from the DETECT_API_KEY env var (OpenAI-compatible endpoint).
DETECT_API_KEY = os.getenv("DETECT_API_KEY", "")
DETECT_API_BASE = os.getenv("DETECT_API_BASE", "https://api.vectorengine.ai/v1")
DETECT_MODEL = os.getenv("DETECT_MODEL", "gemini-3.1-flash-lite")

CACHE_FILE = Path(__file__).resolve().parent.parent / "header_cache.json"


# ── Persistent header dictionary ─────────────────────────────────────────────

def _sig(headers, file_type: str) -> str:
    """Signature = file type + the ordered, stripped header names (binds to col order)."""
    cols = " | ".join(str(h).strip() for h in headers)
    return f"{file_type}::{cols}"


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(data: dict):
    try:
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _cache_get(headers, file_type: str):
    return _load_cache().get(_sig(headers, file_type))


# authority order: a user's manual choice > a shipped seed > an AI guess.
# A lower-authority source never overwrites a higher one (so AI can't clobber a human fix).
_RANK = {"ai": 0, "seed": 1, "user": 2}


def _cache_put(headers, file_type: str, mapping: dict, source: str):
    data = _load_cache()
    key = _sig(headers, file_type)
    existing = data.get(key)
    if existing and _RANK.get(existing.get("source"), 0) > _RANK.get(source, 0):
        return
    data[key] = {**mapping, "source": source}
    _save_cache(data)


# ── LLM detection ────────────────────────────────────────────────────────────

def _headers_and_sample(df: pd.DataFrame, max_rows: int = 4) -> tuple:
    headers = list(df.columns)
    sample_rows = df.head(max_rows).values.tolist()
    sample_rows = [[str(c) if pd.notna(c) else "" for c in row] for row in sample_rows]
    return headers, sample_rows


_DETECT_PROMPT = """你是一个数据分析助手。分析以下 Excel 表格的列名和样本数据，判断每一列的角色。

{context}

列名和样本数据:
{sample}

请只返回一个 JSON 对象，不要任何额外文字:
{output_format}"""


def _ai_detect(df: pd.DataFrame, file_type: str) -> dict:
    headers, sample_rows = _headers_and_sample(df, max_rows=3)
    sample_text = "列名: " + " | ".join(f"[{i}] {h}" for i, h in enumerate(headers)) + "\n"
    for ri, row in enumerate(sample_rows):
        sample_text += f"第{ri+1}行: " + " | ".join(f"[{i}] {cell}" for i, cell in enumerate(row)) + "\n"

    if file_type == "source":
        context = ("这是一个游戏文本文件，需要找出：1) 哪一列包含**需要提取术语的中文原文文本**；"
                   "2) 哪一列是行唯一标识（Key/ID/编号，通常是字符串编码或数字序号），没有则 key_col 为 null；"
                   "3) 哪一列是与原文**逐行对照的英文译文**（整句翻译，不是备注或分类），没有则 en_col 为 null。")
        output_format = '{"text_col": <列索引数字>, "key_col": <列索引数字或null>, "en_col": <列索引数字或null>}'
    else:
        context = ("这是一个游戏术语表文件，需要找出哪一列是**中文术语原文**，哪一列是对应的**英文译文**。"
                   "表中可能还有 Key、分类、备注、来源、审核状态、修订时间等其他列（如「术语分类」是分类标签而非术语本身），不要选这些列。")
        output_format = '{"cn_col": <列索引数字>, "en_col": <列索引数字>}'

    if not DETECT_API_KEY:
        raise RuntimeError("DETECT_API_KEY env var not set (header auto-detection requires an API key)")
    client = OpenAI(api_key=DETECT_API_KEY, base_url=DETECT_API_BASE, timeout=30)
    resp = client.chat.completions.create(
        model=DETECT_MODEL,
        messages=[{"role": "user", "content": _DETECT_PROMPT.format(
            context=context, sample=sample_text, output_format=output_format
        )}],
        temperature=0,
        max_tokens=256,
    )
    raw = resp.choices[0].message.content.strip()
    m = re.search(r"\{[^}]+\}", raw)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


# ── Public API ───────────────────────────────────────────────────────────────

def detect_source_column(df: pd.DataFrame) -> dict:
    """Return {"text_col": int, "key_col": int|None, "en_col": int|None, "method": "cache"|"ai"|"default", "confidence": str}"""
    headers = list(df.columns)
    n = len(headers)
    cached = _cache_get(headers, "source")
    if cached and isinstance(cached.get("text_col"), int) and 0 <= cached["text_col"] < n:
        return {"text_col": cached["text_col"],
                "key_col": cached.get("key_col"),
                "en_col": cached.get("en_col"),
                "method": "cache", "confidence": "高（已知表头，命中字典）"}
    try:
        ai = _ai_detect(df, "source")
        col = ai.get("text_col")
        if col is not None and 0 <= col < n:
            key = ai.get("key_col")
            if key is None or not (0 <= key < n) or key == col:
                key = None
            en = ai.get("en_col")
            if en is None or not (0 <= en < n) or en == col or en == key:
                en = None
            mapping = {"text_col": col, "key_col": key, "en_col": en}
            _cache_put(headers, "source", mapping, "ai")
            return {**mapping, "method": "ai", "confidence": "高（AI 识别）"}
    except Exception:
        pass
    return {"text_col": 0, "key_col": None, "en_col": None, "method": "default", "confidence": "低（默认第一列，请人工确认）"}


def detect_glossary_columns(df: pd.DataFrame) -> dict:
    """Return {"cn_col": int, "en_col": int, "method": "cache"|"ai"|"default", "confidence": str}"""
    headers = list(df.columns)
    n = len(headers)
    cached = _cache_get(headers, "glossary")
    if (cached and isinstance(cached.get("cn_col"), int) and isinstance(cached.get("en_col"), int)
            and 0 <= cached["cn_col"] < n and 0 <= cached["en_col"] < n):
        return {"cn_col": cached["cn_col"], "en_col": cached["en_col"],
                "method": "cache", "confidence": "高（已知表头，命中字典）"}
    try:
        ai = _ai_detect(df, "glossary")
        cn, en = ai.get("cn_col"), ai.get("en_col")
        if (cn is not None and en is not None and cn != en
                and 0 <= cn < n and 0 <= en < n):
            mapping = {"cn_col": cn, "en_col": en}
            _cache_put(headers, "glossary", mapping, "ai")
            return {**mapping, "method": "ai", "confidence": "高（AI 识别）"}
    except Exception:
        pass
    if n >= 2:
        return {"cn_col": 0, "en_col": 1, "method": "default", "confidence": "低（默认前两列，请人工确认）"}
    return {"cn_col": 0, "en_col": 0, "method": "default", "confidence": "低（仅一列）"}


# ── Learning from the user's manual column choice ────────────────────────────

def record_source_correction(headers, text_col, key_col=None, en_col=None):
    """Persist the user's confirmed source-file columns as ground truth."""
    _cache_put(headers, "source",
               {"text_col": int(text_col),
                "key_col": None if key_col is None or int(key_col) < 0 else int(key_col),
                "en_col": None if en_col is None or int(en_col) < 0 else int(en_col)},
               "user")


def record_glossary_correction(headers, cn_col, en_col):
    """Persist the user's confirmed glossary columns as ground truth."""
    _cache_put(headers, "glossary", {"cn_col": int(cn_col), "en_col": int(en_col)}, "user")
