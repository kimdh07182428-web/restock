#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 브랜드스토어(포켓몬) 재입고 감지 스크립트 - DIAGNOSTIC 버전
아직 정확한 셀렉터를 모르므로, 렌더링된 페이지 구조를 로그로 출력해서 파악한다.
"""

import re
import sys

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TARGET_URL = "https://m.brand.naver.com/pokemon/category/c94139abcef14362997090c5da975e28?st=POPULAR&dt=IMAGE&page=1"

SOLDOUT_KEYWORDS = ["품절", "SOLD OUT", "sold out", "일시품절"]


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

        # 혹시 무한스크롤이면 몇 번 스크롤도 시도
        for _ in range(5):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)

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

    found_any = False
    for kw in SOLDOUT_KEYWORDS:
        tags = soup.find_all(string=re.compile(re.escape(kw)))
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
        print("\n[진단] 품절 관련 키워드를 전혀 못 찾았습니다.")
        print("[진단] 본문 앞부분 500자 미리보기:")
        print(body_text[:500])

    # 상품 카드로 추정되는 링크 구조 확인
    product_links = soup.select("a[href*='product'], a[href*='catalog']")
    print(f"\n[진단] 'product' 또는 'catalog'가 포함된 링크 개수: {len(product_links)}")
    for i, a in enumerate(product_links[:8]):
        cls = a.get("class")
        print(f"  링크 {i+1}: href={a.get('href')[:80]} / class={cls} / text={a.get_text(' ', strip=True)[:60]}")

    # 가격이 들어간 요소도 참고로 확인 (보통 상품 카드에 가격이 있음)
    price_tags = soup.find_all(string=re.compile(r"[\d,]+원"))
    print(f"\n[진단] '...원' 패턴 텍스트 개수: {len(price_tags)}")
    for t in price_tags[:5]:
        parent = t.parent
        print(f"  텍스트: {t.strip()[:30]} / 부모 태그: <{parent.name} class='{parent.get('class')}'>" if parent else f"  텍스트: {t.strip()[:30]}")


def main():
    try:
        html = fetch_rendered_html(TARGET_URL)
    except Exception as e:
        print(f"페이지 렌더링 실패: {e}", file=sys.stderr)
        return

    run_diagnostics(html)


if __name__ == "__main__":
    main()
