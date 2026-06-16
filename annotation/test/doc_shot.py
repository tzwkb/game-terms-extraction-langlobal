#!/usr/bin/env python3
# Screenshot the PM operation guide to eyeball branding & layout.
import pathlib
from playwright.sync_api import sync_playwright

DOC = "/Users/spellbook/Desktop/Langlobal/AI Lab/Game-Terms-Extraction-Langlobal/annotation/docs/操作指南_术语标注助手.html"
OUT = str(pathlib.Path(__file__).parent / "doc_shot.png")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1000, "height": 1400}, device_scale_factor=2)
    page.goto(pathlib.Path(DOC).as_uri(), wait_until="networkidle")
    page.screenshot(path=OUT, clip={"x": 0, "y": 0, "width": 1000, "height": 1400})
    print("saved", OUT)
    b.close()
