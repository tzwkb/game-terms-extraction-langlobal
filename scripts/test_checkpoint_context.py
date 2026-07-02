#!/usr/bin/env python3
"""Verify checkpoint terms retain source text and source key (offline, no API)."""

import json
import math
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

sys.modules.setdefault("pandas", types.SimpleNamespace(
    DataFrame=object,
    isna=lambda v: v is None or (isinstance(v, float) and math.isnan(v)),
))
sys.modules.setdefault("yaml", types.SimpleNamespace(safe_load=lambda f: {}))
sys.modules.setdefault("jieba", types.SimpleNamespace(
    cut=lambda s: [],
    suggest_freq=lambda *args, **kwargs: None,
))
sys.modules.setdefault("numpy", types.SimpleNamespace(
    ndarray=object,
    float32=object,
    array=lambda *args, **kwargs: [],
    vstack=lambda rows: rows,
    frombuffer=lambda *args, **kwargs: types.SimpleNamespace(reshape=lambda *a, **k: []),
    argmax=lambda values: 0,
))
sys.modules.setdefault("openai", types.SimpleNamespace(
    AsyncOpenAI=lambda *args, **kwargs: object(),
    OpenAI=lambda *args, **kwargs: object(),
))

import core.main as main


def fake_ner_scan(batch_c, api_key, base_url):
    return [], []


def fake_run_batch_votes(*args, **kwargs):
    vote = {
        "custom_id": "fake",
        "extracted_terms": {
            "terms": [{"term": "墨门", "category": "门派势力"}],
        },
    }
    return [[vote], [vote], [vote]]


orig_ner_scan = main._ner_scan
orig_run_batch_votes = main._run_batch_votes

with tempfile.TemporaryDirectory() as tmp:
    try:
        main._ner_scan = fake_ner_scan
        main._run_batch_votes = fake_run_batch_votes
        ckpt_dir = Path(tmp) / "ckpt"
        texts = ["青长老说墨门弟子需恪守门规"]
        keys = ["DLG_002"]

        returned = main.extract_terms(
            texts,
            {"term_categories": ["门派势力"], "address_suffixes": []},
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="fake-model",
            target_chars=9999,
            output_dir=tmp,
            checkpoint_dir=str(ckpt_dir),
            opts=main.PipelineOpts(max_concurrent=1, max_tokens=1024),
            text_keys=keys,
        )
    finally:
        main._ner_scan = orig_ner_scan
        main._run_batch_votes = orig_run_batch_votes

    ckpt = json.loads((ckpt_dir / "checkpoint.json").read_text(encoding="utf-8"))
    ckpt_term = ckpt["terms"][0]
    returned_term = returned[0]

    cases = [
        ("returned term has source_text", returned_term.get("source_text") == texts[0]),
        ("returned term has source_key", returned_term.get("source_key") == keys[0]),
        ("checkpoint term has source_text", ckpt_term.get("source_text") == texts[0]),
        ("checkpoint term has source_key", ckpt_term.get("source_key") == keys[0]),
    ]

    n_pass = 0
    for name, ok in cases:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        n_pass += ok

    print(f"\n{n_pass}/{len(cases)} passed")
    sys.exit(0 if n_pass == len(cases) else 1)
