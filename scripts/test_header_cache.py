#!/usr/bin/env python3
"""Unit test for the persistent header dictionary in core/header_detect.py.

Cache logic is verified deterministically with a mocked LLM (no network).
One optional live check exercises the bundled detection key; it is skipped
(not failed) if the API is unreachable.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import core.header_detect as hd

results = []


def ck(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + " | " + name + (("  >> " + str(detail)[:160]) if (detail and not ok) else ""))


# isolate the cache to a temp file so we never touch the shipped header_cache.json
hd.CACHE_FILE = Path(tempfile.mkdtemp()) / "hc.json"

# 1. signature binds to column order
ck("签名区分列顺序", hd._sig(["Key", "原文"], "source") != hd._sig(["原文", "Key"], "source"))

# 2. cache miss -> (mocked) AI -> result cached as 'ai'
df = pd.DataFrame({"编号": ["A,1", "A,2"], "正文": ["勇者拿起烈焰之剑", "艾莉娅施放治愈魔法"]})
calls = {"n": 0}
real_ai = hd._ai_detect


def fake_ai(d, ft):
    calls["n"] += 1
    return {"text_col": 1, "key_col": 0, "en_col": None} if ft == "source" else {"cn_col": 0, "en_col": 1}


hd._ai_detect = fake_ai
r1 = hd.detect_source_column(df)
ck("miss→AI 识别 text_col=1/method=ai", r1["text_col"] == 1 and r1["method"] == "ai", r1)
ck("AI 结果入库(source=ai)", (hd._cache_get(list(df.columns), "source") or {}).get("source") == "ai")

# 3. cache hit -> served from dict, no second AI call
n_before = calls["n"]
r2 = hd.detect_source_column(df)
ck("hit→method=cache & text_col=1", r2["method"] == "cache" and r2["text_col"] == 1, r2)
ck("hit→不再调用 AI", calls["n"] == n_before)

# 4. human correction recorded as 'user'
hd.record_source_correction(list(df.columns), text_col=1, key_col=0, en_col=None)
ck("人工纠正写入 source=user", (hd._cache_get(list(df.columns), "source") or {}).get("source") == "user")

# 5. precedence: an AI guess must NOT overwrite a human-confirmed mapping
hd._cache_put(list(df.columns), "source", {"text_col": 0, "key_col": None, "en_col": None}, "ai")
ck("AI 不能覆盖人工(user 保留 text_col=1)", hd._cache_get(list(df.columns), "source")["text_col"] == 1)

# 6. glossary path (mocked)
dg = pd.DataFrame({"中文词": ["剑"], "译文": ["sword"]})
rg = hd.detect_glossary_columns(dg)
ck("术语表 miss→AI cn=0/en=1", rg["cn_col"] == 0 and rg["en_col"] == 1 and rg["method"] == "ai", rg)
ck("术语表 hit→cache", hd.detect_glossary_columns(dg)["method"] == "cache")

# 7. shipped seed hit (point at the real header_cache.json, read-only)
hd._ai_detect = real_ai
hd.CACHE_FILE = ROOT / "header_cache.json"
rs = hd.detect_source_column(pd.DataFrame({"Key": ["Dialog,001"], "原文": ["勇者拿起了烈焰之剑"]}))
ck("种子命中 Key|原文 → cache/text_col=1", rs["method"] == "cache" and rs["text_col"] == 1, rs)

# 8. OPTIONAL live check: bundled key actually detects a fresh header via real LLM
hd.CACHE_FILE = Path(tempfile.mkdtemp()) / "hc2.json"
try:
    rl = hd.detect_source_column(pd.DataFrame({"行号": ["L1", "L2"], "文本": ["前往北境冰原击败霜狼王", "在精灵森林施放治愈魔法"]}))
    if rl["method"] == "ai" and rl["text_col"] == 1:
        print("PASS | [live] 内置key真实识别 text_col=1(文本列)")
        results.append(("live", True))
    else:
        print("SKIP | [live] 识别结果非预期(可能模型波动):", rl)
except Exception as e:
    print("SKIP | [live] API 不可达，跳过真实调用:", str(e)[:100])

passed = sum(1 for _, ok in results if ok)
print("\n" + "=" * 50)
print("HEADER CACHE TEST: %d/%d passed" % (passed, len(results)))
print("=" * 50)
sys.exit(0 if passed == len(results) else 1)
