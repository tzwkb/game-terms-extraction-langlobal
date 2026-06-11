#!/usr/bin/env python3
"""Auto-detect Excel column roles via LLM.

Self-contained by design: detection prompt and API access are hardcoded
in this single file and must not be surfaced in UI/config. Callers pass
only a DataFrame.
"""

import json
import re
import pandas as pd
from openai import OpenAI

DETECT_API_KEY = "***REMOVED-KEY***"
DETECT_API_BASE = "https://api.vectorengine.ai/v1"
DETECT_MODEL = "gemini-3.1-flash-lite"


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
        context = ("这是一个游戏文本文件，需要找出哪一列包含**需要提取术语的原文文本**。"
                   "忽略 Key/ID、编号、备注等辅助列。")
        output_format = '{"text_col": <列索引数字>}'
    else:
        context = ("这是一个游戏术语表文件，需要找出哪一列是**中文术语原文**，哪一列是对应的**英文译文**。"
                   "表中可能还有 Key、分类、备注、来源、审核状态、修订时间等其他列（如「术语分类」是分类标签而非术语本身），不要选这些列。")
        output_format = '{"cn_col": <列索引数字>, "en_col": <列索引数字>}'

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


# ── Public API ───────────────────────────────────────────

def detect_source_column(df: pd.DataFrame) -> dict:
    """Return {"text_col": int, "method": "ai"|"default", "confidence": str}"""
    try:
        ai = _ai_detect(df, "source")
        col = ai.get("text_col")
        if col is not None and 0 <= col < len(df.columns):
            return {"text_col": col, "method": "ai", "confidence": "高（AI 识别）"}
    except Exception:
        pass
    return {"text_col": 0, "method": "default", "confidence": "低（默认第一列，请人工确认）"}


def detect_glossary_columns(df: pd.DataFrame) -> dict:
    """Return {"cn_col": int, "en_col": int, "method": "ai"|"default", "confidence": str}"""
    try:
        ai = _ai_detect(df, "glossary")
        cn, en = ai.get("cn_col"), ai.get("en_col")
        if (cn is not None and en is not None and cn != en
                and 0 <= cn < len(df.columns) and 0 <= en < len(df.columns)):
            return {"cn_col": cn, "en_col": en, "method": "ai", "confidence": "高（AI 识别）"}
    except Exception:
        pass
    n = len(df.columns)
    if n >= 2:
        return {"cn_col": 0, "en_col": 1, "method": "default", "confidence": "低（默认前两列，请人工确认）"}
    return {"cn_col": 0, "en_col": 0, "method": "default", "confidence": "低（仅一列）"}
