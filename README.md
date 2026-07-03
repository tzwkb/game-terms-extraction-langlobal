# Game Terms Extraction Tool

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-app-ff4b4b.svg)](https://streamlit.io/)

English | [中文](README_ZH.md)

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

The following code blocks keep commands, paths, filenames, and configuration keys literal; explanatory comments are translated for the English README.

```bash
pip install -r requirements.txt
streamlit run ui/app.py
```

```
source.xlsx + glossary.xlsx
  ├─ AI column auto-detection (source column / Key column / bilingual English column / glossary ZH-EN columns)
  ├─ NER pre-scan (names/places)
  ├─ LLM term extraction (3-round voting; keep unanimous items)
  ├─ vector embedding match (exact hits use glossary entries)
  └─ LLM translation (new terms)
        ├─ results.xlsx (raw results with debug fields)
        └─ 候选术语_模板.xlsx (8-column annotation template with source-row Key; review_status=unreviewed)
```

```
├── core/
│   ├── main.py             # pipeline orchestration
│   ├── llm_extractor.py    # term extraction (3-round voting)
│   ├── llm_translator.py   # term translation
│   ├── embed_store.py      # vector store (SQLite + text-embedding-3-large)
│   ├── checkpoint.py       # checkpoint and resume support
│   ├── header_detect.py    # header auto-detection
│   └── prompt_base.py      # prompt construction
├── ui/
│   ├── app.py              # Streamlit frontend
│   └── ui_backend.py       # UI adapter layer
├── annotation/             # term annotation assistant (human review workbench, single HTML)
├── scripts/                # validation and evaluation scripts
├── profiles/               # game profile files (YAML)
├── database/               # vector-store cache (generated)
├── output/                 # run outputs (generated)
├── config.py               # engine parameters (copied from config_template.py)
├── config_template.py      # config template
├── run.bat                 # one-click Windows launcher
├── setup.bat               # automatic Python environment setup
└── requirements.txt
```

## Detailed Technical Notes

The primary README keeps the original technical details, history notes, full commands, and file layout. This file maintains the English version of the core documentation; consult the primary README code blocks and paths when exact commands are needed.
