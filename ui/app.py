"""Streamlit UI for Game-Terms-Extraction pipeline."""

from __future__ import annotations

import sys
import json
import hashlib
import shutil
import tempfile
import time
import datetime
from io import BytesIO
from pathlib import Path
import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from ui.ui_backend import (
    RunConfig, default_config, ProcessingTask,
    get_all_models, add_custom_model, remove_model,
    list_profiles, save_uploaded_profile, delete_profile,
    test_api_connection, get_profile_template, get_profile_content,
    save_persisted_config, check_checkpoint,
    reset_embed_db, embed_db_term_count,
    load_ckpt_meta,
)

st.set_page_config(page_title="游戏术语提取工具", page_icon="🎮", layout="wide")

# ═══════════════════════════════════════════════════════════
# Session state init
# ═══════════════════════════════════════════════════════════

DEFAULTS = {
    "cfg": None,
    "task": None,
    "task_results": None,
    "sel_model": "",
    "sel_profile": "",
    "api_test_result": None,
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

if st.session_state.cfg is None:
    cfg = default_config()
    models = get_all_models()
    profiles = list_profiles()
    if cfg.model not in models:
        cfg.model = models[0] if models else ""
    if cfg.profile not in profiles:
        cfg.profile = profiles[0] if profiles else ""
    st.session_state.cfg = cfg

# Resolve pending widget changes from previous handler runs (before any widget renders)
for _key in ("sel_model", "sel_profile", "_src_col", "_gl_cn_col", "_gl_en_col"):
    _pending = f"_pending_{_key}"
    if _pending in st.session_state:
        st.session_state[_key] = st.session_state.pop(_pending)


def _sync_cfg():
    cfg = st.session_state.cfg
    m = st.session_state.get("sel_model", "")
    p = st.session_state.get("sel_profile", "")
    if m:
        cfg.model = m
    if p:
        cfg.profile = p


# ═══════════════════════════════════════════════════════════
# Page router
# ═══════════════════════════════════════════════════════════

PAGES = {"运行": "process", "设置": "settings", "结果": "results"}

with st.sidebar:
    st.title("🎮 游戏术语提取工具")
    page = st.radio("页面", list(PAGES.keys()), label_visibility="collapsed")

page_id = PAGES[page]

# ═══════════════════════════════════════════════════════════
# Page: Settings
# ═══════════════════════════════════════════════════════════

if page_id == "settings":
    st.header("设置")

    cfg = st.session_state.cfg

    # ── API ──────────────────────────────────────────
    st.subheader("API 配置")
    col1, col2 = st.columns(2)
    with col1:
        cfg.api_key = st.text_input("API Token", value=cfg.api_key, type="password",
                                    help="OpenAI 兼容的 API Token")
    with col2:
        cfg.api_base = st.text_input("API 地址", value=cfg.api_base,
                                     help="OpenAI 兼容的 Base URL")

    # ── Model ────────────────────────────────────────
    st.subheader("模型")
    all_models = get_all_models()

    col_m1, col_m2, col_m3 = st.columns([3, 1, 1])
    with col_m1:
        if all_models:
            cur = st.session_state.sel_model or cfg.model
            idx = all_models.index(cur) if cur in all_models else 0
            st.selectbox("选择模型", all_models, index=idx, key="sel_model")
        else:
            st.text_input("模型名称", key="sel_model")
        _sync_cfg()

    with col_m2:
        new_model = st.text_input("添加模型", placeholder="模型名", label_visibility="collapsed")
        if st.button("添加", use_container_width=True):
            if new_model.strip():
                add_custom_model(new_model.strip())
                st.session_state._pending_sel_model = new_model.strip()
                _sync_cfg()
                st.rerun()

    with col_m3:
        delete_disabled = len(all_models) <= 1
        if st.button("删除", use_container_width=True, disabled=delete_disabled, help="删除当前选中的模型"):
            remove_model(st.session_state.sel_model)
            remaining = get_all_models()
            st.session_state._pending_sel_model = remaining[0] if remaining else ""
            _sync_cfg()
            st.rerun()

    # ── Advanced Settings ────────────────────────────
    with st.expander("高级设置", expanded=False):
        st.subheader("项目配置（Profile）")

        profiles = list_profiles()

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            if profiles:
                cur = st.session_state.sel_profile or cfg.profile
                idx = profiles.index(cur) if cur in profiles else 0
                st.selectbox("已有配置", profiles, index=idx, key="sel_profile",
                             help="选择项目 YAML 配置")
            else:
                st.text_input("配置名称", key="sel_profile")
            _sync_cfg()

        with col_p2:
            uploaded_yaml = st.file_uploader(
                "上传新配置", type=["yaml", "yml"],
                help="上传 YAML 文件，自动保存到 profiles/ 并出现在左侧列表",
            )
            if uploaded_yaml is not None:
                try:
                    name = save_uploaded_profile(uploaded_yaml.name, uploaded_yaml.getvalue())
                    st.session_state._pending_sel_profile = name
                    _sync_cfg()
                    st.success(f"已保存: {name}.yaml")
                    st.rerun()
                except Exception as e:
                    st.error(f"YAML 格式错误: {e}")

        if st.session_state.sel_profile:
            content = get_profile_content(st.session_state.sel_profile)
            col_d1, col_d2, _ = st.columns([1, 1, 4])
            with col_d1:
                if content:
                    st.download_button(
                        f"下载 {st.session_state.sel_profile}.yaml",
                        data=content,
                        file_name=f"{st.session_state.sel_profile}.yaml",
                        mime="text/yaml",
                        use_container_width=True,
                    )
            with col_d2:
                disabled = len(profiles) <= 1
                if st.button("删除此配置", use_container_width=True, disabled=disabled):
                    delete_profile(st.session_state.sel_profile)
                    remaining = list_profiles()
                    st.session_state._pending_sel_profile = remaining[0] if remaining else ""
                    _sync_cfg()
                    st.rerun()

        st.divider()
        template = get_profile_template()
        if template:
            st.download_button(
                "下载 YAML 配置模板",
                data=template,
                file_name="profile_template.yaml",
                mime="text/yaml",
                help="下载一份空白配置模板，供 PM 填写后上传",
            )


        st.divider()
        st.subheader("向量库管理")
        db_count = embed_db_term_count()
        if db_count > 0:
            st.caption(f"当前向量库：{db_count} 条术语")
            st.info(
                "**正常情况下无需手动重置。** 每次运行时，新增的术语会自动加入向量库。\n\n"
                "仅在以下情况点击重置：\n"
                "- 切换了 Embedding 模型（切换后旧向量无效）\n"
                "- 术语表大幅缩减、需要清除旧向量\n"
                "- 向量库出现异常"
            )
            if st.button("重置向量库（下次运行时重建）", type="secondary"):
                reset_embed_db()
                st.success("向量库已删除，下次运行时将自动全量重建。")
                st.rerun()
        else:
            st.caption("向量库尚未构建，首次运行时将自动创建。")

        st.divider()

        cfg.max_concurrent = st.slider("LLM 提取并发", 1, 100, cfg.max_concurrent,
                                       help="同时发起的 LLM 提取请求数")
        cfg.embed_workers = st.slider("Embedding 并发", 1, 100, cfg.embed_workers,
                                      help="同时发起的向量编码 API 请求数")


    st.divider()
    st.caption("设置已自动保存，刷新浏览器后自动恢复。")
    cfg_sig = (cfg.api_key, cfg.model, cfg.profile, cfg.api_base)
    if st.session_state.get("_saved_cfg") != cfg_sig:
        save_persisted_config(cfg)
        st.session_state._saved_cfg = cfg_sig

# ═══════════════════════════════════════════════════════════
# Page: Process
# ═══════════════════════════════════════════════════════════

elif page_id == "process":
    st.header("运行")

    cfg = st.session_state.cfg
    _sync_cfg()

    col1, col2 = st.columns(2)
    with col1:
        src_file = st.file_uploader("原文文件（xlsx）", type=["xlsx"], key="src_upload",
                                    on_change=lambda: st.session_state.pop("_col_detected", None))
    with col2:
        gl_file = st.file_uploader("术语表文件（xlsx）", type=["xlsx"], key="gl_upload",
                                   on_change=lambda: st.session_state.pop("_col_detected", None))

    # Cache uploads so files survive page navigation
    if src_file is not None:
        st.session_state["_src_cache"] = (src_file.name, src_file.getvalue())
    if gl_file is not None:
        st.session_state["_gl_cache"] = (gl_file.name, gl_file.getvalue())

    _src_cache = st.session_state.get("_src_cache")
    _gl_cache = st.session_state.get("_gl_cache")

    if src_file is None and _src_cache:
        c1, c2 = st.columns([6, 1])
        c1.caption(f"原文已缓存: `{_src_cache[0]}`")
        if c2.button("清除", key="clr_src"):
            del st.session_state["_src_cache"]
            st.session_state.pop("_col_detected", None)
            st.rerun()
    if gl_file is None and _gl_cache:
        c1, c2 = st.columns([6, 1])
        c1.caption(f"术语表已缓存: `{_gl_cache[0]}`")
        if c2.button("清除", key="clr_gl"):
            del st.session_state["_gl_cache"]
            st.session_state.pop("_col_detected", None)
            st.rerun()

    eff_src = src_file.getvalue() if src_file else (_src_cache[1] if _src_cache else None)
    eff_src_name = src_file.name if src_file else (_src_cache[0] if _src_cache else "")
    eff_gl = gl_file.getvalue() if gl_file else (_gl_cache[1] if _gl_cache else None)
    eff_gl_name = gl_file.name if gl_file else (_gl_cache[0] if _gl_cache else "")

    # ── Column detection (auto on upload) ──────────
    src_col = st.session_state.get("_src_col", 0)
    gl_cn_col = st.session_state.get("_gl_cn_col", 0)
    gl_en_col = st.session_state.get("_gl_en_col", 1)

    if eff_src and eff_gl and not st.session_state.get("_col_detected"):
        from core.header_detect import detect_source_column, detect_glossary_columns
        try:
            df_src = pd.read_excel(BytesIO(eff_src))
            df_gl = pd.read_excel(BytesIO(eff_gl))
            d_src = detect_source_column(df_src, cfg.api_key, cfg.api_base)
            d_gl = detect_glossary_columns(df_gl, cfg.api_key, cfg.api_base)
            st.session_state._pending__src_col = d_src["text_col"]
            st.session_state._pending__gl_cn_col = d_gl["cn_col"]
            st.session_state._pending__gl_en_col = d_gl["en_col"]
            st.session_state._col_info = {"src": d_src, "gl": d_gl}
        except Exception:
            st.session_state._col_info = {}
        st.session_state._col_detected = True
        st.rerun()

    col_info = st.session_state.get("_col_info", {})
    if col_info:
        src = col_info.get("src", {})
        gl = col_info.get("gl", {})
        st.caption(f"原文列: {src.get('method','?')}（{src.get('confidence','?')}） | "
                   f"术语列: {gl.get('method','?')}（{gl.get('confidence','?')}）")

        if eff_src:
            df_src = pd.read_excel(BytesIO(eff_src))
            src_headers = [str(c) for c in df_src.columns]
            st.selectbox("原文列", range(len(src_headers)),
                         index=min(st.session_state.get("_src_col", 0), len(src_headers) - 1),
                         format_func=lambda i: f"[{i}] {src_headers[i]}",
                         key="_src_col")
        if eff_gl:
            df_gl = pd.read_excel(BytesIO(eff_gl))
            gl_headers = [str(c) for c in df_gl.columns]
            c1, c2 = st.columns(2)
            with c1:
                st.selectbox("中文术语列", range(len(gl_headers)),
                             index=min(st.session_state.get("_gl_cn_col", 0), len(gl_headers) - 1),
                             format_func=lambda i: f"[{i}] {gl_headers[i]}",
                             key="_gl_cn_col")
            with c2:
                st.selectbox("英文翻译列", range(len(gl_headers)),
                             index=min(st.session_state.get("_gl_en_col", 1), len(gl_headers) - 1),
                             format_func=lambda i: f"[{i}] {gl_headers[i]}",
                             key="_gl_en_col")

        src_col = st.session_state.get("_src_col", 0)
        gl_cn_col = st.session_state.get("_gl_cn_col", 0)
        gl_en_col = st.session_state.get("_gl_en_col", 1)

    # ── Checkpoint status ──────────────────────
    ckpt_root = Path("output") / "_checkpoints"
    all_ckpts = []
    if ckpt_root.exists():
        for d in sorted(ckpt_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            ckpt_file = d / "checkpoint.json"
            if d.is_dir() and ckpt_file.exists():
                try:
                    data = json.loads(ckpt_file.read_text(encoding="utf-8"))
                    if data.get("chunk_idx", 0) > 0:
                        meta = load_ckpt_meta(str(d))
                        all_ckpts.append({
                            "name": d.name,
                            "chunk_idx": data["chunk_idx"],
                            "total": data.get("total_chunks", 0),
                            "terms": len(data.get("terms", [])),
                            "src_col": meta.get("src_col", 0),
                            "gl_cn_col": meta.get("gl_cn_col", 0),
                            "gl_en_col": meta.get("gl_en_col", 1),
                            "src_filename": meta.get("src_filename", ""),
                            "gl_filename": meta.get("gl_filename", ""),
                            "mtime": d.stat().st_mtime,
                        })
                except Exception:
                    pass

    # Auto-save uploaded files to matching checkpoint
    if eff_src and eff_gl and ckpt_root.exists():
        h = hashlib.md5(eff_src).hexdigest()[:8]
        for d in ckpt_root.iterdir():
            if d.is_dir() and h in d.name and cfg.profile in d.name:
                sp = d / "source.xlsx"
                gp = d / "glossary.xlsx"
                if not sp.exists():
                    sp.write_bytes(eff_src)
                if not gp.exists():
                    gp.write_bytes(eff_gl)
                break

    # Per-file match
    if eff_src:
        ckpt = check_checkpoint(eff_src, cfg.profile)
        if ckpt["exists"]:
            st.success(f"该文件可续传: 已处理 {ckpt['chunk_idx']}/{ckpt['total_chunks']} chunks，已有 {ckpt['terms']} 条术语")

    if all_ckpts:
        with st.expander(f"所有断点 ({len(all_ckpts)} 个)", expanded=len(all_ckpts) <= 3):
            for c in all_ckpts:
                src_path = ckpt_root / c["name"] / "source.xlsx"
                gl_path = ckpt_root / c["name"] / "glossary.xlsx"
                has_files = src_path.exists() and gl_path.exists()
                col_c1, col_c2, col_c3 = st.columns([3, 1, 1])
                with col_c1:
                    extra = "" if has_files else " (需上传文件才能继续)"
                    fn_info = f"  `{c['src_filename']}`" if c.get("src_filename") else ""
                    ts = datetime.datetime.fromtimestamp(c.get("mtime", 0)).strftime("%m-%d %H:%M")
                    st.caption(f"{ts} · {c['chunk_idx']}/{c['total']} chunks · {c['terms']} 条术语{fn_info}{extra}")
                with col_c2:
                    if st.button("继续", key=f"resume_{c['name']}", disabled=not has_files, use_container_width=True):
                        task = ProcessingTask()
                        task.start(str(src_path), str(gl_path), cfg,
                                   src_col=c.get("src_col", 0),
                                   gl_cn_col=c.get("gl_cn_col", 0),
                                   gl_en_col=c.get("gl_en_col", 1),
                                   src_bytes=src_path.read_bytes())
                        st.session_state.task = task
                        st.session_state.task_results = None
                        st.session_state._results_saved = False
                        st.rerun()
                with col_c3:
                    if st.button("删除", key=f"del_ckpt_{c['name']}", use_container_width=True):
                        shutil.rmtree(ckpt_root / c["name"])
                        st.rerun()

    if eff_src and eff_gl and cfg.profile:
        st.caption(f"配置: `{cfg.profile}` | 模型: `{cfg.model}` | 匹配: embedding | 并发: {cfg.max_concurrent}")

    st.divider()

    can_run = (
        eff_src is not None
        and eff_gl is not None
        and cfg.api_key
        and cfg.model
        and cfg.profile
        and (st.session_state.task is None or not st.session_state.task.is_running)
    )

    col_btn1, col_btn2, _ = st.columns([1, 1, 4])
    with col_btn1:
        if st.button("开始提取", type="primary", disabled=not can_run, use_container_width=True):
            tmp_dir = Path(tempfile.mkdtemp())
            src_path = tmp_dir / eff_src_name
            gl_path = tmp_dir / eff_gl_name
            src_path.write_bytes(eff_src)
            gl_path.write_bytes(eff_gl)

            task = ProcessingTask()
            task.start(str(src_path), str(gl_path), cfg,
                       src_col=src_col, gl_cn_col=gl_cn_col, gl_en_col=gl_en_col,
                       src_bytes=eff_src)
            st.session_state.task = task
            st.session_state.task_results = None
            st.session_state._results_saved = False
            st.rerun()

    with col_btn2:
        task: ProcessingTask = st.session_state.task
        running = task is not None and task.is_running
        if st.button("取消", disabled=not running, use_container_width=True):
            if task:
                task.cancel()
            st.rerun()

    st.divider()

    task: ProcessingTask = st.session_state.task
    if task is not None:

        @st.fragment(run_every=0.5)
        def _progress_fragment():
            if task._cancelling:
                st.warning("已取消")
                st.session_state.task = None
                return

            if task.done:
                if task.error:
                    if "Cancelled" in str(task.error):
                        st.warning("已取消")
                    else:
                        st.error(f"运行失败: {task.error}")
                else:
                    st.success(f"完成 — 共提取 {len(task.results)} 条术语")
                    st.session_state.task_results = task.results
                    if not st.session_state.get("_results_saved"):
                        out_path = (Path(task.output_dir) / "results.xlsx"
                                    if task.output_dir
                                    else ROOT / "output" / f"results_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
                        pd.DataFrame(task.results).to_excel(out_path, index=False)
                        st.session_state._results_saved = True
                st.session_state.task = None
                return

            stage_labels = {
                "starting": "初始化中…",
                "loading": "加载文件…",
                "extracting": "LLM 术语提取（3轮投票）",
                "translating": "匹配 + 翻译术语",
                "done": "完成",
            }

            label = stage_labels.get(task.stage, task.stage)
            total = task.stage_total
            done = task.stage_done
            if total > 1:
                pct = min(done / total, 1.0)
                st.progress(pct, text=f"{label} — {done}/{total}")
            elif done >= total and total > 0:
                st.progress(1.0, text=label)
            else:
                st.progress(0.0, text=label)

            if task.info:
                st.caption(task.info)

        _progress_fragment()

    if st.session_state.task_results is not None and st.session_state.task_results:
        st.divider()
        st.subheader("预览")
        df = pd.DataFrame(st.session_state.task_results)
        cols = ["term", "category", "translation", "match_type"]
        display_cols = [c for c in cols if c in df.columns]
        if display_cols:
            st.dataframe(df[display_cols], use_container_width=True, height=400)

# ═══════════════════════════════════════════════════════════
# Page: Results
# ═══════════════════════════════════════════════════════════

elif page_id == "results":
    st.header("结果")

    results = st.session_state.task_results

    if results is None or len(results) == 0:
        st.info("当前 Session 暂无结果，请先在「运行」页面执行提取，或加载下方历史文件。")
        out_root = ROOT / "output"
        saved = sorted(
            out_root.glob("run_*/results.xlsx"), key=lambda f: f.stat().st_mtime, reverse=True
        ) if out_root.exists() else []
        if saved:
            st.subheader("历史结果")
            for f in saved:
                run_name = f.parent.name
                ts = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                c1, c2, c3 = st.columns([4, 1, 1])
                c1.caption(f"`{run_name}` — {ts}")
                with c2:
                    st.download_button("下载", data=f.read_bytes(),
                                       file_name=f"{run_name}_results.xlsx",
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       key=f"dl_{f.name}", use_container_width=True)
                with c3:
                    if st.button("加载", key=f"load_{f.name}", use_container_width=True):
                        st.session_state.task_results = pd.read_excel(f).to_dict("records")
                        st.rerun()
    else:
        df = pd.DataFrame(results)
        st.metric("术语总数", len(results))

        st.subheader("匹配分布")
        if "match_type" in df.columns:
            match_counts = df["match_type"].value_counts()
            labels_cn = {"exact": "精确匹配", "llm_translated": "LLM 翻译"}
            cols = st.columns(len(match_counts))
            for i, (label, count) in enumerate(match_counts.items()):
                cols[i].metric(labels_cn.get(label, label), count)

        st.subheader("分类分布")
        if "category" in df.columns:
            cat_counts = df["category"].value_counts()
            st.bar_chart(cat_counts)

        st.subheader("全部术语")
        st.dataframe(df, use_container_width=True, height=400)

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="terms")
        output.seek(0)

        st.download_button(
            "下载结果 xlsx",
            data=output,
            file_name="terms_extraction_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

# ═══════════════════════════════════════════════════════════
# Sidebar footer
# ═══════════════════════════════════════════════════════════

with st.sidebar:
    st.divider()
    cfg = st.session_state.cfg
    _sync_cfg()

    st.caption(f"模型: `{cfg.model}`")
    st.caption(f"配置: `{cfg.profile}`")
    st.caption(f"LLM并发: {cfg.max_concurrent} | Embed并发: {cfg.embed_workers}")

    if st.button("测试 API 连接", use_container_width=True):
        with st.spinner("正在测试…"):
            ok, msg = test_api_connection(cfg)
            st.session_state.api_test_result = (ok, msg)

    if st.session_state.api_test_result is not None:
        ok, msg = st.session_state.api_test_result
        if ok:
            st.success(msg)
        else:
            st.error(msg)
