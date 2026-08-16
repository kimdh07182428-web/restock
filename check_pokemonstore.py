#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
포켓몬 스토어(pokemonstore.co.kr) 재입고 감지 스크립트 - Playwright 버전
이 사이트는 자바스크립트로 렌더링되므로 requests 대신 실제 브라우저(Playwright)로 접근.

DIAGNOSTIC 모드: 아직 정확한 셀렉터를 모르기 때문에, 렌더링된 페이지에서
"품절" 텍스트가 어떻게 나오는지 로그로 출력합니다. 이 로그를 보고 파싱 로직을 확정합니다.
"""

import json
import os
import re
import sys

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ── 설정 ──────────────────────────────────────────────
TARGET_URL = "https://m.pokemonstore.co.kr/pages/product/product-list.html?categoryNo=488339"
STATE_FILE = os.path.join(os.path.dirname(__file__), "state_pokemonstore.json")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "CHANGE_ME_TO_RANDOM_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

SOLDOUT_KEYWORDS = ["품절", "SOLD OUT", "sold out", "품절임박"]


def fetch_rendered_html(url: str) -> str:
    """Playwright로 실제 브라우저처럼 페이지를 열고, JS 렌더링이 끝난 뒤의 HTML을 반환."""
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
    """'품절' 텍스트 주변 구조를 로그로 출력해서, 정확한 셀렉터를 파악하기 위한 진단 함수."""
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text(" ", strip=True)

    print("=" * 60)
    print("[진단] 페이지 title:", soup.title.string if soup.title else "(없음)")
    print("[진단] 렌더링된 본문 글자 수:", len(body_text))
    print("[진단] '품절' 텍스트가 페이지에 존재하는가:", "품절" in body_text)
    print("=" * 60)

    found_any = False
    for kw in SOLDOUT_KEYWORDS:
        tags = [t for t in soup.find_all(string=re.compile(re.escape(kw)))]
        if not tags:
            continue
        found_any = True
        print(f"\n[진단] 키워드 '{kw}' 발견 개수: {len(tags)}")
        for i, t in enumerate(tags[:5]):
            parent = t.parent
            grandparent = parent.parent if parent else None
            print(f"  --- 발견 {i+1} ---")
            print(f"  텍스트: {t.strip()[:50]}")
            print(f"  부모 태그: <{parent.name} class='{parent.get('class')}'>" if parent else "  부모 없음")
            if grandparent:
                print(f"  조부모 태그: <{grandparent.name} class='{grandparent.get('class')}'>")

    if not found_any:
        print("\n[진단] '품절' 관련 키워드를 전혀 못 찾았습니다.")
        print("[진단] 페이지 본문 앞부분 500자 미리보기:")
        print(body_text[:500])

    product_links = soup.select("a[href*='product']")
    print(f"\n[진단] 'product'가 포함된 링크 개수: {len(product_links)}")
    for i, a in enumerate(product_links[:5]):
        print(f"  링크 {i+1}: href={a.get('href')} / class={a.get('class')} / text={a.get_text(strip=True)[:30]}")


def main():
    try:
        html = fetch_rendered_html(TARGET_URL)
    except Exception as e:
        print(f"페이지 렌더링 실패: {e}", file=sys.stderr)
        return

    run_diagnostics(html)


if __name__ == "__main__":
    main()
