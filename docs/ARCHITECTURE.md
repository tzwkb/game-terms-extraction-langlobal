# Architecture

## Module Map

```
cli.py                   ← CLI 入口（argparse）
ui/app.py                ← 前端入口（Streamlit）→ ui/ui_backend.py 编排
core/main.py             ← 引擎库，对外暴露 run_pipeline / extract_terms（无 __main__）
  │
  ├── profiles/<game>.yaml   ← 项目配置（每个项目一个文件）
  ├── config.py              ← 引擎参数（并发、超时、投票温度）
  ├── prompt_base.py         ← prompt 构造（系统 + 用户 + 翻译）
  ├── llm_extractor.py       ← LLMExtractor（异步批量提取）
  ├── llm_translator.py      ← TermTranslator（批量翻译）
  ├── embed_store.py         ← EmbedStore（SQLite 向量库，本地 bge-m3）
  ├── checkpoint.py          ← 断点续跑
  └── logger.py              ← 日志配置
```

---

## Public Interfaces

### `main.py`

#### `run_pipeline` — 完整工作流入口
```python
run_pipeline(
    source_path: str,            # 源文本 Excel
    glossary_path: str,          # 术语表 Excel
    profile_name: str = "yanyun",
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gemini-3.1-pro-preview",
    output_dir: str = "",
    raw_dir: str = "",
    checkpoint_dir: str = "",
    progress_callback: callable = None,
    opts: PipelineOpts = PipelineOpts(),  # bilingual/no_translate/src_col/src_en_col/key_col/gl_cn_col/gl_en_col/并发
) -> List[dict]
```
返回术语列表，每项：
```json
{
  "term": "墨门",
  "category": "门派势力",
  "source_text": "青长老说墨门弟子需恪守门规",
  "source_key": "DLG_001",
  "translation": "Momen",
  "match_type": "exact | bilingual | llm_translated | no_translate",
  "note": "（可选）EN列与术语表冲突时记录EN原值",
  "ref_term": "...",
  "ref_trans": "...",
  "ref_sim": 0.92
}
```

#### `results_to_template_df` / `save_outputs` — 标注模板导出
```python
results_to_template_df(results: List[dict], timestamp: str = "") -> pd.DataFrame
# 8 列模板（TEMPLATE_COLUMNS）：Key值/术语分类/术语原文/术语译文/备注/来源原文/审核状态/最新修订时间

save_outputs(results: List[dict], out_dir) -> Tuple[Path, Path]
# 同时落盘 results.xlsx + 候选术语_模板.xlsx，CLI 与 UI 共用
```

#### `extract_terms` — 仅提取，不翻译
```python
extract_terms(
    texts: List[str],
    profile: dict,
    api_key: str,
    base_url: str,
    model: str,
    target_chars: int = 1200,    # 每个 chunk 的目标字符数
    max_tokens: int = None,      # 默认读 EXTRACTOR_CONFIG
    concurrent: int = None,
    output_dir: str = "",
    raw_dir: str = "",
    checkpoint_dir: str = "",
    glossary_keys: set = None,
) -> List[dict]
```
返回 `[{"term": str, "category": str, "source_text": str}, ...]`

#### `match_and_translate` — 仅翻译
```python
match_and_translate(
    extracted: List[dict],
    glossary: dict,              # {cn_lower: (cn, en)}
    profile: dict,
    api_key: str,
    base_url: str,
    model: str,
    similarity: str = "embedding",
    raw_dir: str = "",
    embed_store: EmbedStore = None,
) -> List[dict]
```

#### `load_config` / `load_glossary`
```python
load_config(profile_name: str) -> dict
load_glossary(path: str) -> Tuple[dict, set]   # (glossary_dict, keys_set)
```

#### `filter_derived_terms`
```python
filter_derived_terms(
    terms: List[dict],
    address_suffixes: list,      # 从 profile["address_suffixes"] 读取
    glossary_keys: set = None,
) -> List[dict]
```
过滤称谓派生变体（如冯大哥→冯），glossary 中的词豁免。

---

### `LLMExtractor`（llm_extractor.py）

```python
extractor = LLMExtractor(
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    base_dir: str = "output",    # API 日志目录
    cache_dir: str = "",         # 请求级缓存目录（空=禁用）
)
```

**主要方法：**

```python
# 异步（在已有 event loop 内调用）
await extractor.run_batch_async(
    texts: List[str],
    system_prompt: str,
    user_prompts: List[str],
    model: str,
    temperature: float,
    max_tokens: int,
    max_concurrent: int,
    source_files: List[str],
    batch_id: str = "",
) -> List[dict]

# 同步封装（会自己 asyncio.run）
extractor.process_batch_concurrent(
    texts, system_prompt, user_prompts, model,
    temperature, max_tokens, max_concurrent, source_files, batch_id,
) -> List[dict]
```

每个结果项：
```json
{
  "custom_id": "b0_v0_t0",
  "extracted_terms": {"terms": [...]},
  "usage": {"total_tokens": 1200, "prompt_tokens": 900, "completion_tokens": 300},
  "model": "...",
  "source_file": "c0",
  "created": 1716123456
}
```

---

### `TermTranslator`（llm_translator.py）

```python
translator = TermTranslator(
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o",
    profile: dict = None,
)

translator.translate_with_hints(
    system_prompt: str,
    user_prompt: str,
) -> Dict[str, str]   # {"墨门": "Momen", ...}
```

---

### `prompt_base.py`

```python
build_system_prompt(profile: dict) -> str

build_user_prompt(
    profile: dict,
    text: str,
    include_context: bool = True,
    bilingual: bool = False,       # 双语文本（ZH: ... | EN: ...）
    jieba_hints: list = None,      # 术语表命中提示词
    ner_hints: dict = None,        # {"persons": [...], "places": [...]}
) -> str

build_translation_prompt(
    profile: dict,
    terms_with_ref: list,          # 每项含 _ref_term / _ref_trans / source_text
) -> tuple[str, str]               # (system_prompt, user_prompt)
```

---

### `EmbedStore`（embed_store.py）

```python
store = EmbedStore(
    db_path: str,                  # SQLite 文件路径
    model: str = "E:/huggingface/models/bge-m3",
    device: str = "cpu",
)

store.is_built -> bool             # 库是否已建好
store.count -> int                 # 已存词条数

store.build(terms: list, batch_size: int = 256)   # 构建/增量更新
store.search(queries: list) -> list[tuple[str, float]]  # [(最近邻词, 相似度), ...]
```

---

### `checkpoint.py`

```python
task_id(source_path: str, profile: str) -> str   # 由文件哈希生成，用作 checkpoint 目录名
load(checkpoint_dir: str) -> dict                # {"chunk_idx": int, "terms": list, "total_chunks": int}
save(checkpoint_dir: str, chunk_idx: int, terms: list, total_chunks: int)
clear(checkpoint_dir: str)                       # 任务完成后清除
```

---

### `config.py`（常量）

```python
VOTE_TEMPS = [0, 0.3, 0.7]        # 三次投票的温度

EXTRACTOR_CONFIG = {
    "max_tokens": 65536,
    "max_concurrent": 10,
    "timeout": 120.0,
    "max_retries": 3,
}

TRANSLATOR_CONFIG = {
    "temperature": 0.1,
    "max_tokens": 65536,
    "max_concurrent": 10,
    "timeout": 120.0,
    "max_retries": 3,
}

get_token_param_name(model: str) -> str   # "max_tokens" or "max_output_tokens"
```

---

## Profile 字段参考（YAML）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `game_type` | str | — | 注入 system prompt 的游戏类型描述；默认 `"游戏"` |
| `term_categories` | list[str] | — | LLM 可用的全部分类名；默认 `[]`（prompt 中无分类约束） |
| `task_description` | str | — | 任务标签，仅作文档说明，代码不读取 |
| `filterable_categories` | list[str] | — | 提取后可过滤的分类（通用/噪音类）；默认 `[]`，不过滤 |
| `address_suffixes` | list[str] | — | 称谓后缀（如大哥、嫂子），用于去派生变体；默认 `[]`，不过滤 |
| `extraction_notes` | list[str] | — | 追加到 user prompt 的补充规则 |
| `extract_examples.include` | list[str] | — | system prompt 中的正例 |
| `extract_examples.exclude` | list[str] | — | system prompt 中的负例 |
| `fewshot_examples` | list[dict] | — | `{input, output}` 格式的 few-shot 样本 |
| `fewshot_examples_bilingual` | list[dict] | — | 双语模式专用 few-shot（output 含 zh_term/eng_term）；双语时优先于 `fewshot_examples` |
| `translation_rules` | list[str] | — | 翻译风格规则，注入翻译 prompt |
| `rule_extractors.surname_names` | dict | — | 基于姓氏的规则抽取（燕云专用） |
| `core_principle` | str | — | 追加到 system prompt 开头的核心原则 |

---

## Data Flow

```
source.xlsx (A列原文)
  │
  ├─ load_excel → List[str] (去重、去变量占位符)
  ├─ _chunk_texts → List[chunk]  (每块 ~1200 字)
  │
  ├─ 每批 chunk（10并发）:
  │     ├─ NER Flash Lite → persons / places
  │     ├─ rule_extractors → rule_persons
  │     ├─ build_user_prompt (含 ner_hints + jieba_hints)
  │     └─ LLMExtractor × 3投票 (temp=0/0.3/0.7)
  │           → 3/3 投票通过 → 候选术语
  │
  ├─ filter_derived_terms (去除称谓派生变体)
  ├─ profile.filterable_categories 过滤（非术语库中的通用分类）
  │
  ├─ 译文权威序（2026-06-12 裁决）:
  │     ① glossary 精确命中 → exact（与双语EN列冲突时译文取库、EN原值写 note）
  │     ② 双语EN列照抄 → bilingual
  │     ③ EmbedStore top-1 + LLM 翻译 → llm_translated（注入 translation_rules）
  │
  └─ save_outputs → results.xlsx + 候选术语_模板.xlsx（8列，审核状态=未审核，note→备注）
```

---

## CLI

```bash
# 完整流水线（CLI 入口为根目录 cli.py，调用 core.main.run_pipeline）
python cli.py \
  --source test_file/原文.xlsx \
  --glossary test_file/【日更】0514术语表.xlsx \
  --profile yanyun \
  --api-key sk-... \
  --base-url https://api.vectorengine.ai/v1 \
  --model gemini-3.1-pro-preview \
  --output output/run_20260520

# 双语模式（原文含中英两列，英文照抄不重译）
python cli.py --source 双语原文.xlsx --glossary 术语表.xlsx \
  --profile xiuxiu --bilingual --src-col 0 --src-en-col 1 --api-key sk-...

# 评估（提取 + P/R/F1 对比人工术语表）
python eval.py \
  --source test_file/原文.xlsx \
  --manual test_file/人工术语_cleaned.xlsx \
  --profile yanyun
```
