#!/usr/bin/env python3
# Render the tool with sample data and capture screenshots to eyeball layout.
import os
import tempfile
import pathlib
from openpyxl import Workbook
from playwright.sync_api import sync_playwright

HTML = "/Users/spellbook/Desktop/Langlobal/AI Lab/Game-Terms-Extraction-Langlobal/annotation/术语标注助手_v3.0.html"
OUT = os.path.dirname(os.path.abspath(__file__))


def make_xlsx():
    path = os.path.join(tempfile.gettempdir(), "shot_src.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "English", "原文", "译文"])
    for r in [["k1", "Fireball", "火球术", "火球"],
              ["k2", "Heal", "治疗术", "治疗"],
              ["k3", "FireballDup", "火球术", "火球"],
              ["k4", "Shield", "护盾术", "护盾"],
              ["k5", "Frost", "冰霜术", "冰霜"]]:
        ws.append(r)
    wb.save(path)
    return path


def add_term(page, t):
    page.click("#btnAddTerm")
    page.wait_for_selector("#adTerm")
    page.fill("#adTerm", t)
    page.click("#adOk")
    page.wait_for_timeout(250)


def main():
    xlsx = make_xlsx()
    url = pathlib.Path(HTML).as_uri()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 950})
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("#btnAddTerm")
        with page.expect_file_chooser() as fc:
            page.click("#btnImportSrc")
        fc.value.set_files(xlsx)
        page.wait_for_selector("#wrap table thead th")
        for t in ["火球术", "治疗术", "护盾术"]:
            add_term(page, t)
        page.wait_for_timeout(400)
        top = os.path.join(OUT, "shot_top.png")
        page.screenshot(path=top, clip={"x": 0, "y": 0, "width": 1500, "height": 950})
        print("saved", top)
        b.close()


if __name__ == "__main__":
    main()
