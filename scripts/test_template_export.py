#!/usr/bin/env python3
"""Verify pipeline results -> unified 8-column annotation template (offline, no API)."""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.main import (
    DEFAULT_TEMPLATE_FILENAME,
    TEMPLATE_COLUMNS,
    descriptive_template_filename,
    results_to_template_df,
    save_outputs,
)

RESULTS = [
    {"term": "墨门", "category": "门派势力", "source_text": "青长老说墨门弟子需恪守门规",
     "source_key": "DLG_001", "note": "EN列与术语表不一致，EN列原文：Mo Sect",
     "translation": "Momen", "match_type": "exact", "ref_term": "墨门", "ref_trans": "Momen", "ref_sim": 1.0},
    {"term": "八荒剑诀", "category": "技能", "source_text": "习得八荒剑诀第一式",
     "translation": "", "match_type": "no_translate"},
    {"term": "青长老", "category": "人名", "source_text": float("nan"),
     "translation": None, "match_type": "llm_translated"},
]

df = results_to_template_df(RESULTS, timestamp="2026-06-11T12:00:00")

def value(row, col):
    return df.loc[row, col] if col in df.columns else None

with tempfile.TemporaryDirectory() as tmp:
    res_path, tpl_path = save_outputs(
        RESULTS,
        tmp,
        profile_name="yanyun",
        source_path="【英】非重点内容 0630【global_pre】【国服0529版本NKC】.xlsx",
        run_date="20260702",
    )
    saved_files = {p.name for p in Path(tmp).glob("*.xlsx")}
    save_outputs_ok = (
        res_path.name == "results.xlsx"
        and tpl_path.name == "燕云_国服0529NKC_global_pre_非重点内容0630_候选术语标注表_20260702.xlsx"
        and DEFAULT_TEMPLATE_FILENAME not in saved_files
        and tpl_path.name in saved_files
        and len(saved_files) == 2
    )

CASES = [
    ("column order matches template", list(df.columns) == TEMPLATE_COLUMNS),
    ("row count", len(df) == 3),
    ("term -> 术语原文", df.loc[0, "术语原文"] == "墨门"),
    ("translation -> 术语译文", df.loc[0, "术语译文"] == "Momen"),
    ("source_text -> 来源原文", df.loc[0, "来源原文"] == "青长老说墨门弟子需恪守门规"),
    ("source_key -> Key值", df.loc[0, "Key值"] == "DLG_001"),
    ("missing source_key -> empty Key值", df.loc[1, "Key值"] == "" and df.loc[2, "Key值"] == ""),
    ("remarks column renamed to match source", "匹配来源" in df.columns and "备注" not in df.columns),
    ("exact match source value is direct", value(0, "匹配来源") == "精确匹配"),
    ("no_translate match source value is direct", value(1, "匹配来源") == "无需翻译"),
    ("AI translation match source value is direct", value(2, "匹配来源") == "AI翻译"),
    ("审核状态 all 未审核", (df["审核状态"] == "未审核").all()),
    ("timestamp applied", (df["最新修订时间"] == "2026-06-11T12:00:00").all()),
    ("NaN/None -> empty string", df.loc[2, "来源原文"] == "" and df.loc[2, "术语译文"] == ""),
    ("empty results -> header-only df", list(results_to_template_df([]).columns) == TEMPLATE_COLUMNS),
    ("default timestamp ISO-like", "T" in results_to_template_df(RESULTS[:1]).loc[0, "最新修订时间"]),
    ("descriptive template filename keeps project/batch/date",
     descriptive_template_filename(
         profile_name="yanyun",
         source_path="【英】非重点内容 0630【global_pre】【国服0529版本NKC】.xlsx",
         run_date="20260702",
     ) == "燕云_国服0529NKC_global_pre_非重点内容0630_候选术语标注表_20260702.xlsx"),
    ("descriptive template filename falls back to legacy default without context",
     descriptive_template_filename() == DEFAULT_TEMPLATE_FILENAME),
    ("save_outputs writes only results and the descriptive template when context exists", save_outputs_ok),
]

n_pass = 0
for name, ok in CASES:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    n_pass += ok

print(f"\n{n_pass}/{len(CASES)} passed")
sys.exit(0 if n_pass == len(CASES) else 1)
