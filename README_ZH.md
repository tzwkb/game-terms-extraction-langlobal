# 游戏术语提取工具

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-app-ff4b4b.svg)](https://streamlit.io/)

[English](README.md) | 中文

从游戏中文文本中自动提取术语并翻译成英文，输出可直接交付的双语术语表 xlsx。

## 快速启动

**Windows：双击 `run.bat`**（首次运行会自动安装 Python 和依赖）

手动启动：
```bash
pip install -r requirements.txt
streamlit run ui/app.py
```

> 首次使用需配置 API Key，见 [部署指南](docs/DEPLOY.md)。

## 工作流

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

## 人工审校闭环（标注工具）

提取结果不是终点：`候选术语_模板.xlsx` 导入配套的 **[术语标注助手](annotation/README.md)**（`annotation/术语标注助手_v3.0.html`，浏览器双击即用）做人工标注审核，导出的审定术语表可直接回流本工具作为下次提取的术语表输入。

CLI 绑定源文件 Key 列用 `--key-col <列索引>`；UI 上传后自动识别，可手动改。

## 目录结构

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

## Profile 配置

每个游戏项目对应一个 `profiles/*.yaml`，控制提取规则、术语分类、翻译策略。

- 在 UI「设置 → 高级设置」中上传 YAML 文件
- 或直接放入 `profiles/` 目录后重启

## 断点续跑

任务中断后重新上传相同文件、选相同 profile，UI 会自动检测断点并从上次位置继续。

## License

[MIT](LICENSE)
