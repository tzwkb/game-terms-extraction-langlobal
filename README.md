# 游戏术语提取工具

[中文](README_ZH.md) | English


## Overview

 Game terminology extraction pipeline that uses an LLM to extract terms from Chinese game text and produce deliverable bilingual glossaries.

## Key Capabilities

- Identifies term candidates from game text.
- Generates English renderings and glossary fields.
- Outputs deliverable xlsx files.

## Usage

 Prepare source text according to the README input format and run the extraction scripts.

## Status

 This repository is maintained or used according to the current README notes.

## Notes

 Terminology output should be reviewed by localization staff before delivery.

## Command and Configuration Reference

The following code blocks are preserved from the primary README. Commands, paths, and configuration keys are not translated; adjust them for the actual environment.

```bash
pip install -r requirements.txt
streamlit run ui/app.py
```

```
原文.xlsx + 术语表.xlsx
  ├─ AI 列自动识别（原文列 / Key列 / 双语英文列 / 术语表中英列）
  ├─ NER 预扫描（人名/地名）
  ├─ LLM 术语提取（3轮投票，取3票一致项）
  ├─ 向量嵌入匹配（精确命中走术语表）
  └─ LLM 翻译（新术语）
        ├─ results.xlsx（原始结果，含调试字段）
        └─ 候选术语_模板.xlsx（8列标注模板，含来源行 Key，审核状态=未审核）
```

```
├── core/
│   ├── main.py             # 流水线编排
│   ├── llm_extractor.py    # 术语提取（3轮投票）
│   ├── llm_translator.py   # 术语翻译
│   ├── embed_store.py      # 向量库（SQLite + text-embedding-3-large）
│   ├── checkpoint.py       # 断点续跑
│   ├── header_detect.py    # 表头自动识别
│   └── prompt_base.py      # Prompt 构造
├── ui/
│   ├── app.py              # Streamlit 前端
│   └── ui_backend.py       # UI 适配层
├── annotation/             # 术语标注助手（人工审校工作台，单HTML）
├── scripts/                # 验证与评估脚本
├── profiles/               # 游戏配置文件（YAML）
├── database/               # 向量库缓存（自动生成）
├── output/                 # 运行结果（自动生成）
├── config.py               # 引擎参数（从 config_template.py 复制）
├── config_template.py      # 配置模板
├── run.bat                 # Windows 一键启动
├── setup.bat               # 自动安装 Python 环境
└── requirements.txt
```

## Detailed Technical Notes

The primary README keeps the original technical details, history notes, full commands, and file layout. This file maintains the English version of the core documentation; consult the primary README code blocks and paths when exact commands are needed.
