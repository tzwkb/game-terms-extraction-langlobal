#!/usr/bin/env python3
# Smoke test for 术语标注助手 (single-file HTML tool).
# Drives a real headless Chromium via Playwright: loads the page, verifies the
# post-edit structure, then exercises the core end-to-end flows.
# Run:  python3 smoke_test.py
import os
import sys
import tempfile
import pathlib

HTML = "/Users/spellbook/Desktop/Langlobal/AI Lab/Game-Terms-Extraction-Langlobal/annotation/术语标注助手_v3.0.html"

try:
    from openpyxl import Workbook
    from playwright.sync_api import sync_playwright
except Exception as e:  # noqa
    print("DEP-MISSING:", e)
    sys.exit(2)

results = []


def check(name, cond, detail=""):
    cond = bool(cond)
    results.append((name, cond, detail))
    line = ("PASS" if cond else "FAIL") + " | " + name
    if not cond and detail:
        line += "  >> " + str(detail)[:200]
    print(line, flush=True)


def run(name, fn):
    """Run a step that returns (ok, detail); never aborts the suite."""
    try:
        ok, detail = fn()
    except Exception as e:  # noqa
        ok, detail = False, "EXC %s: %s" % (type(e).__name__, e)
    check(name, ok, detail)


def make_xlsx():
    path = os.path.join(tempfile.gettempdir(), "smoke_src.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "English", "原文", "译文"])  # col index 2 (C) = term column (default termCol)
    data = [
        ["k1", "Fireball", "火球术", "火球"],
        ["k2", "Heal", "治疗术", "治疗"],
        ["k3", "FireballDup", "火球术", "火球"],
        ["k4", "Shield", "护盾术", "护盾"],
        ["k5", "Frost", "冰霜术", "冰霜"],
    ]
    for r in data:
        ws.append(r)
    wb.save(path)
    return path, len(data)


def make_xlsx2():
    # 原文 deliberately in column A (index 0), not the default col C, to prove header detection
    path = os.path.join(tempfile.gettempdir(), "smoke_src2.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.append(["原文", "译文", "Key", "备注"])
    for r in [["闪电术", "闪电", "k1", ""], ["寒冰箭", "寒冰", "k2", ""]]:
        ws.append(r)
    wb.save(path)
    return path


def term_count(page):
    t = (page.locator("#termCount").inner_text() or "0").strip()
    return int("".join(ch for ch in t if ch.isdigit()) or "0")


def main():
    xlsx, n_rows = make_xlsx()
    xlsx2 = make_xlsx2()
    url = pathlib.Path(HTML).as_uri()
    console_errors = []
    page_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(8000)
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())  # auto-accept native confirm() (btnNew)

        # 1. load
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("#btnAddTerm")
        page.wait_for_timeout(300)
        run("page loads, no error on load",
            lambda: (len(page_errors) == 0 and len(console_errors) == 0,
                     "pageerr=%s console=%s" % (page_errors[:2], console_errors[:2])))

        # 2. structural assertions (verify the edits)
        run("title has name, no version 'v3.0'",
            lambda: ("术语标注助手" in page.title() and "v3.0" not in page.title(), page.title()))
        run("h1 is plain name (badge removed)",
            lambda: (page.locator(".app-header h1").inner_text().strip() == "术语标注助手",
                     page.locator(".app-header h1").inner_text()))
        run("capacity badge removed", lambda: (page.locator("#capBadge").count() == 0, ""))
        run("footer-note removed", lambda: (page.locator(".footer-note").count() == 0, ""))
        run("no '性能版' text in body",
            lambda: ("性能版" not in page.locator("body").inner_text(), ""))
        run("no 'v3.0' in visible text",
            lambda: ("v3.0" not in page.locator("body").inner_text(), ""))
        # integration: 快速术语添加 moved into sidebar term-section, out of filter-bar
        run("btnBatchMode in main-panel filter-bar (near table)",
            lambda: (page.locator(".filter-bar #btnBatchMode").count() == 1, ""))
        run("btnBatchMode gone from sidebar (no redundant add pair)",
            lambda: (page.locator(".sidebar #btnBatchMode").count() == 0, ""))
        run("sidebar keeps only manual-add + tags",
            lambda: (page.locator(".sidebar #btnAddTerm").count() == 1
                     and page.locator(".sidebar #btnTags").count() == 1
                     and page.locator(".sidebar #btnBatchMode").count() == 0, ""))
        # jump-row relocated to filter-bar (near the table)
        run("jump-row moved into filter-bar",
            lambda: (page.locator(".filter-bar #jumpInput").count() == 1
                     and page.locator(".filter-bar #btnJump").count() == 1, ""))
        run("jump-row gone from project-bar",
            lambda: (page.locator(".project-bar #jumpInput").count() == 0, ""))
        run("clear-terms moved to sidebar (danger), gone from import toolbar",
            lambda: (page.locator(".sidebar #btnClearTerms").count() == 1
                     and page.locator(".toolbar #btnClearTerms").count() == 0, ""))
        run("entry buttons carry effect tooltips",
            lambda: (all(page.locator("#" + b).get_attribute("title")
                         for b in ["btnNew", "btnLoad", "btnImportSrc", "btnImportTerms"]), ""))

        # 3. import source xlsx -> main grid renders
        def do_import():
            with page.expect_file_chooser() as fc:
                page.click("#btnImportSrc")
            fc.value.set_files(xlsx)
            page.wait_for_selector("#wrap table thead th", timeout=8000)
            th = page.locator("#wrap table thead th").count()
            tr = page.locator("#wrap table tbody tr").count()
            srows = page.evaluate("() => { try { return S.rows.length } catch(e) { return -1 } }")
            ok = th >= 4 and tr >= 1 and (srows == n_rows or srows == -1)
            return ok, "th=%s tr=%s S.rows=%s" % (th, tr, srows)
        run("import xlsx renders grid (headers+rows)", do_import)

        # 4. manual add term
        def do_add():
            before = term_count(page)
            page.click("#btnAddTerm")
            page.wait_for_selector("#adTerm")
            page.fill("#adTerm", "火球术")
            page.click("#adOk")
            page.wait_for_timeout(400)
            after = term_count(page)
            in_list = page.locator(".term-item:has-text('火球术')").count() >= 1
            return (after == before + 1 and in_list), "count %s->%s in_list=%s" % (before, after, in_list)
        run("manual add term (dialog) increments library", do_add)

        # 5. search
        def do_search():
            page.fill("#termSearch", "火球")
            page.wait_for_timeout(300)
            hit = page.locator(".term-item:has-text('火球术')").count() >= 1
            page.fill("#termSearch", "zzz_no_such_term")
            page.wait_for_timeout(300)
            empty = page.locator(".term-item").count() == 0
            page.fill("#termSearch", "")
            page.wait_for_timeout(200)
            return (hit and empty), "hit=%s empty_on_nomatch=%s" % (hit, empty)
        run("term search filters list", do_search)

        # 6. filters
        def do_filters():
            page.select_option("#fStatus", "pending")
            page.select_option("#fSort", "time_desc")
            page.select_option("#fCat", "all")
            page.wait_for_timeout(200)
            page.select_option("#fStatus", "all")
            page.select_option("#fSort", "default")
            page.wait_for_timeout(150)
            return True, ""
        run("sidebar filters change without error", do_filters)

        # 7. batch mode (integrated 快速术语添加) full flow
        def do_batch():
            page.click("#btnBatchMode")
            page.wait_for_timeout(250)
            disp_on = page.eval_on_selector("#batchBar", "el => getComputedStyle(el).display")
            page.click("#btnSelAll")
            page.wait_for_timeout(200)
            page.click("#btnBatchAdd")
            page.wait_for_selector("#bcOk")
            before = term_count(page)
            page.click("#bcOk")
            page.wait_for_timeout(500)
            after = term_count(page)
            page.click("#btnBatchExit")
            page.wait_for_timeout(200)
            disp_off = page.eval_on_selector("#batchBar", "el => getComputedStyle(el).display")
            ok = disp_on != "none" and after > before and disp_off == "none"
            return ok, "bar_on=%s bar_off=%s count %s->%s" % (disp_on, disp_off, before, after)
        run("batch quick-add: bar toggles + adds rows as terms", do_batch)

        # 8. tag manager
        def do_tags():
            page.click("#btnTags")
            page.wait_for_timeout(300)
            opened = page.locator(".dialog:has-text('分类标签')").count() >= 1
            if page.locator("#tgClose").count():
                page.click("#tgClose")
            page.wait_for_timeout(200)
            return opened, "opened=%s" % opened
        run("tag manager opens", do_tags)

        # 9. jump row (relocated control still works)
        def do_jump():
            page.fill(".filter-bar #jumpInput", "2")
            page.click(".filter-bar #btnJump")
            page.wait_for_timeout(250)
            return True, ""
        run("jump-to-row control works", do_jump)

        # 10. export terms -> download
        def do_export():
            with page.expect_download(timeout=8000) as dl:
                page.click("#btnExport")
            fn = dl.value.suggested_filename
            return bool(fn), "file=%s" % fn
        run("export terms triggers download", do_export)

        # 10.5 source-column auto-detection: 原文 in col A must be detected, not default col C
        def do_autodetect():
            with page.expect_file_chooser() as fc:
                page.click("#btnImportSrc")
            fc.value.set_files(xlsx2)
            # wait until the NEW workbook is actually loaded (header already existed from prior import,
            # so wait on S.headers reflecting xlsx2 — termCol is set synchronously right after)
            page.wait_for_function(
                "() => { try { return S.headers && S.headers[0] === '原文' && S.headers.length === 4 } catch(e) { return false } }",
                timeout=8000)
            tc = page.evaluate("() => S.termCol")
            return tc == 0, "termCol=%s (expected 0; 原文 is in col A)" % tc
        run("source column auto-detected by header (原文 in col A)", do_autodetect)

        # 11. reset project: clears, then auto-opens import picker (reset->import chain)
        def do_new():
            with page.expect_file_chooser(timeout=6000) as fc:
                page.click("#btnNew")  # confirm() auto-accepted, then import picker auto-opens
            nc = term_count(page)       # terms cleared by new project
            fc.value.set_files(xlsx)    # chain feeds source -> re-imports
            page.wait_for_selector("#wrap table thead th", timeout=8000)
            rows = page.evaluate("() => { try { return S.rows.length } catch(e) { return -1 } }")
            return (nc == 0 and rows >= 1), "termsAfterClear=%s reimportedRows=%s" % (nc, rows)
        run("reset project clears + auto-opens import (chain)", do_new)

        # 12. final error tally across whole run
        run("no uncaught page errors during run",
            lambda: (len(page_errors) == 0, "; ".join(page_errors[:3])))
        run("no console errors during run",
            lambda: (len(console_errors) == 0, "; ".join(console_errors[:3])))

        browser.close()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 48)
    print("SMOKE SUMMARY: %d/%d passed" % (passed, total))
    if passed != total:
        print("FAILED:")
        for name, ok, detail in results:
            if not ok:
                print("  - %s  %s" % (name, detail))
    print("=" * 48)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
