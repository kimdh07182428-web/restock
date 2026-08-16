#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 브랜드스토어(포켓몬) 재입고 감지 스크립트 - DIAGNOSTIC 버전 v2
네이버가 클라우드 IP를 차단할 수 있어 재시도 로직 추가.
"""

import re
import sys

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TARGET_URL = "https://m.brand.naver.com/pokemon/category/c94139abcef14362997090c5da975e28?st=POPULAR&dt=IMAGE&page=1"

SOLDOUT_KEYWORDS = ["품절", "SOLD OUT", "sold out", "일시품절"]

BLOCK_INDICATORS = ["에러페이지", "접속이 불가", "일시적으로 제한"]


def fetch_rendered_html(url: str, attempt_label: str = "") -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
        )
        page.set_extra_http_headers({
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://www.naver.com/",
        })
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        for _ in range(5):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)

        html = page.content()
        browser.close()
        return html


def is_blocked(html: str) -> bool:
    return any(kw in html for kw in BLOCK_INDICATORS)


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

    product_links = soup.select("a[href*='product'], a[href*='catalog']")
    print(f"\n[진단] 'product' 또는 'catalog'가 포함된 링크 개수: {len(product_links)}")
    for i, a in enumerate(product_links[:8]):
        cls = a.get("class")
        print(f"  링크 {i+1}: href={a.get('href')[:80]} / class={cls} / text={a.get_text(' ', strip=True)[:60]}")

    price_tags = soup.find_all(string=re.compile(r"[\d,]+원"))
    print(f"\n[진단] '...원' 패턴 텍스트 개수: {len(price_tags)}")
    for t in price_tags[:5]:
        parent = t.parent
        print(f"  텍스트: {t.strip()[:30]} / 부모 태그: <{parent.name} class='{parent.get('class')}'>" if parent else f"  텍스트: {t.strip()[:30]}")

    # 상품 링크 하나를 골라서, 조상 태그를 5단계까지 올라가며 각 단계의 전체 텍스트를 출력
    # -> 상품명/가격이 몇 단계 위 컨테이너에 들어있는지 파악하기 위함
    real_product_links = [a for a in product_links if "/products/" in (a.get("href") or "")]
    if real_product_links:
        sample = real_product_links[0]
        print(f"\n[진단] 샘플 상품 링크 조상 태그 단계별 탐색 (href={sample.get('href')})")
        node = sample
        for level in range(6):
            if node is None:
                break
            text = node.get_text(" ", strip=True)
            print(f"  레벨 {level}: <{node.name} class='{node.get('class')}'> 텍스트: {text[:150]}")
            node = node.parent


def main():
    html = None
    for attempt in range(1, 4):
        print(f"\n[시도 {attempt}] 페이지 요청 중...")
        try:
            candidate = fetch_rendered_html(TARGET_URL, attempt_label=str(attempt))
        except Exception as e:
            print(f"[시도 {attempt}] 렌더링 실패: {e}", file=sys.stderr)
            continue

        if is_blocked(candidate):
            print(f"[시도 {attempt}] 차단 페이지 감지됨. 재시도 대기...")
            import time
            time.sleep(5)
            continue

        html = candidate
        print(f"[시도 {attempt}] 정상 페이지 수신 성공")
        break

    if html is None:
        print("\n[결론] 모든 시도에서 차단 페이지가 나왔습니다. 클라우드 IP 차단으로 판단됩니다.")
        return

    run_diagnostics(html)


if __name__ == "__main__":
    main()
