#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
포켓몬 스토어(pokemonstore.co.kr) 재입고 감지 스크립트 - Playwright 버전
DIAGNOSTIC 모드: 상품 카드(thumb-item) 내부 구조를 로그로 출력.
"""

import json
import os
import re
import sys

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TARGET_URL = "https://m.pokemonstore.co.kr/pages/product/product-list.html?categoryNo=488339"
STATE_FILE = os.path.join(os.path.dirname(__file__), "state_pokemonstore.json")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "CHANGE_ME_TO_RANDOM_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

SOLDOUT_KEYWORDS = ["품절", "SOLD OUT", "sold out", "품절임박"]


def fetch_rendered_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
            ),
            viewport={"width": 390, "height": 844},
        )
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()
        return html


def run_diagnostics(html: str):
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text(" ", strip=True)

    print("=" * 60)
    print("[진단] 페이지 title:", soup.title.string if soup.title else "(없음)")
    print("[진단] 렌더링된 본문 글자 수:", len(body_text))
    print("=" * 60)

    thumb_items = soup.select("a.thumb-item")
    print(f"\n[진단] 'thumb-item' 카드 개수: {len(thumb_items)}")
    for i, a in enumerate(thumb_items[:8]):
        has_soldout = "SOLD OUT" in a.get_text()
        print(f"\n  --- 카드 {i+1} (품절여부: {has_soldout}) ---")
        print(f"  href: {a.get('href')}")
        print(f"  전체 텍스트: {a.get_text(' ', strip=True)[:150]}")
        print(f"  내부 태그 구조:")
        for child in a.find_all(True, recursive=True):
            cls = child.get("class")
            txt = child.get_text(strip=True)[:40]
            if txt:
                print(f"    <{child.name} class={cls}> {txt}")


def main():
    try:
        html = fetch_rendered_html(TARGET_URL)
    except Exception as e:
        print(f"페이지 렌더링 실패: {e}", file=sys.stderr)
        return

    run_diagnostics(html)


if __name__ == "__main__":
    main()
