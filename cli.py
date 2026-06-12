#!/usr/bin/env python3
"""命令行入口。前端入口为 ui/app.py，两者共用 core.main.run_pipeline。"""
import os, time, argparse
from pathlib import Path

from core.main import run_pipeline, PipelineOpts, save_outputs
from core.checkpoint import checkpoint_dir_name
from config_template import DEFAULT_API_BASE, DEFAULT_MODEL, DEFAULT_PROFILE, DEFAULT_EMBED_WORKERS


def main():
    parser = argparse.ArgumentParser(description="游戏术语提取 CLI")
    parser.add_argument("--source", required=True, help="源文件 xlsx")
    parser.add_argument("--glossary", required=True, help="术语表 xlsx（不需要可传空表）")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help=f"配置名 (default: {DEFAULT_PROFILE})")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""))
    parser.add_argument("--base-url", default=DEFAULT_API_BASE, help=f"(default: {DEFAULT_API_BASE})")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"(default: {DEFAULT_MODEL})")
    parser.add_argument("--output", default="")
    parser.add_argument("--checkpoint", default="",
                        help="Checkpoint dir for resumable runs (auto-generated if not set)")
    parser.add_argument("--src-col", type=int, default=0, help="原文文本列索引")
    parser.add_argument("--key-col", type=int, default=None,
                        help="源文件 Key/ID 列索引（可选，填充导出模板的 Key值 列）")
    parser.add_argument("--gl-cn-col", type=int, default=0, help="术语表中文列索引")
    parser.add_argument("--gl-en-col", type=int, default=1, help="术语表英文列索引")
    parser.add_argument("--bilingual", action="store_true",
                        help="双语模式：原文含中英两列，英文直接照抄不重译")
    parser.add_argument("--src-en-col", type=int, default=1,
                        help="双语模式下原文的英文列索引")
    parser.add_argument("--no-translate", action="store_true",
                        help="跳过 LLM 翻译，仅提取术语（双语模式照抄 EN 列）")
    parser.add_argument("--concurrent", type=int, default=None, help="并发数")
    parser.add_argument("--max-tokens", type=int, default=None, help="单次最大 token")
    parser.add_argument("--embed-workers", type=int, default=DEFAULT_EMBED_WORKERS, help="向量同步并发")
    args = parser.parse_args()

    t0 = time.time()
    out_dir = args.output or f"output/run_{time.strftime('%Y%m%d_%H%M')}"
    raw_dir = f"{out_dir}/raw_data"
    ckpt_dir = args.checkpoint or f"output/_checkpoints/{checkpoint_dir_name(Path(args.source).read_bytes(), args.profile)}"

    opts = PipelineOpts(
        bilingual=args.bilingual, no_translate=args.no_translate,
        src_col=args.src_col, src_en_col=args.src_en_col, key_col=args.key_col,
        gl_cn_col=args.gl_cn_col, gl_en_col=args.gl_en_col,
        embed_workers=args.embed_workers,
        max_concurrent=args.concurrent, max_tokens=args.max_tokens,
    )
    results = run_pipeline(args.source, args.glossary, args.profile,
                           args.api_key, args.base_url, args.model,
                           raw_dir=raw_dir, checkpoint_dir=ckpt_dir,
                           opts=opts)

    save_outputs(results, out_dir)
    print(f"\nDone. {len(results)} terms. Output: {out_dir} (results.xlsx + 候选术语_模板.xlsx)")
    print(f"Total: {(time.time()-t0)/60:.1f}m")


if __name__ == "__main__":
    main()
