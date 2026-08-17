#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 브랜드스토어(포켓몬) 재입고 감지 스크립트 - 최종본 v5 (페이지네이션 방식)
GitHub Actions에서 5분마다 실행 -> 재입고 감지되면 ntfy.sh로 폰에 푸시 알림.
"""

import json
import os
import re
import sys
import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_LIST_URL = "https://m.brand.naver.com/pokemon/category/c94139abcef14362997090c5da975e28?st=POPULAR&dt=IMAGE"
BASE_URL = "https://m.brand.naver.com"
STATE_FILE = os.path.join(os.path.dirname(__file__), "state_naverstore.json")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "CHANGE_ME_TO_RANDOM_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

BLOCK_INDICATORS = ["에러페이지", "접속이 불가", "일시적으로 제한"]
MAX_PAGES = 20  # 안전장치: 최대 20페이지 (페이지당 40개면 최대 800개 커버)


def fetch_all_pages() -> dict:
    """productNo -> {"name": str, "soldout": bool, "url": str} 딕셔너리 반환. 페이지를 넘기며 전체 수집."""
    result = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page_obj = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
        )
        page_obj.set_extra_http_headers({
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://www.naver.com/",
        })

        for page_num in range(1, MAX_PAGES + 1):
            url = f"{BASE_LIST_URL}&page={page_num}"

            html = None
            for attempt in range(1, 4):
                try:
                    page_obj.goto(url, wait_until="networkidle", timeout=30000)
                    page_obj.wait_for_timeout(2000)
                    candidate = page_obj.content()
                except Exception as e:
                    print(f"[페이지 {page_num}, 시도 {attempt}] 렌더링 실패: {e}", file=sys.stderr)
                    continue

                if is_blocked(candidate):
                    print(f"[페이지 {page_num}, 시도 {attempt}] 차단 페이지 감지됨. 재시도 대기...")
                    time.sleep(5)
                    continue

                html = candidate
                break

            if html is None:
                print(f"[페이지 {page_num}] 모든 시도 실패, 이 페이지는 건너뜁니다.", file=sys.stderr)
                break

            page_products = parse_products(html)

            if not page_products:
                print(f"[정보] 페이지 {page_num}에서 상품을 못 찾음 -> 마지막 페이지로 판단하고 종료")
                break

            new_count = 0
            for product_no, info in page_products.items():
                if product_no not in result:
                    new_count += 1
                result[product_no] = info

            print(f"[정보] 페이지 {page_num}: {len(page_products)}개 파싱, 신규 {new_count}개 (누적 {len(result)}개)")

            if new_count == 0:
                print(f"[정보] 페이지 {page_num}에서 전부 중복 -> 마지막 페이지로 판단하고 종료")
                break

        browser.close()

    return result


def is_blocked(html: str) -> bool:
    return any(kw in html for kw in BLOCK_INDICATORS)


def parse_products(html: str) -> dict:
    """productNo -> {"name": str, "soldout": bool, "url": str} 딕셔너리 반환."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("li.Hz4XxKbt9h")

    result = {}
    for card in cards:
        link = card.select_one("a[href*='/products/']")
        if not link:
            continue
        href = link.get("href", "")
        m = re.search(r"/products/(\d+)", href)
        if not m:
            continue
        product_no = m.group(1)

        name_tag = card.select_one("strong.xSW7C99vO3")
        name = name_tag.get_text(strip=True) if name_tag else f"상품 {product_no}"

        is_soldout = card.find(string=re.compile("품절")) is not None

        full_url = BASE_URL + href if href.startswith("/") else href

        result[product_no] = {"name": name, "soldout": is_soldout, "url": full_url}

    return result


def load_prev_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def notify(title: str, message: str, click_url: str = None):
    if NTFY_TOPIC == "CHANGE_ME_TO_RANDOM_TOPIC":
        print("[경고] NTFY_TOPIC이 기본값입니다.", file=sys.stderr)

    headers = {
        "Title": title.encode("utf-8"),
        "Priority": "urgent",
        "Tags": "warning,shopping",
    }
    if click_url:
        headers["Click"] = click_url

    try:
        import requests
        requests.post(NTFY_URL, data=message.encode("utf-8"), headers=headers, timeout=10)
    except Exception as e:
        print(f"ntfy 알림 전송 실패: {e}", file=sys.stderr)


def main():
    current = fetch_all_pages()

    if not current:
        print("상품을 하나도 못 찾았습니다. 사이트 구조가 바뀌었거나 일시적으로 차단됐을 수 있습니다.")
        return

    prev = load_prev_state()

    restocked = []
    for product_no, info in current.items():
        prev_info = prev.get(product_no)
        was_soldout = prev_info["soldout"] if prev_info else None
        if was_soldout is True and info["soldout"] is False:
            restocked.append(info)

    if restocked:
        for item in restocked:
            notify("네이버 포켓몬 스토어 재입고!", item["name"], click_url=item["url"])
            print(f"재입고 감지 -> 알림 전송: {item['name']} ({item['url']})")
    else:
        soldout_count = sum(1 for v in current.values() if v["soldout"])
        print(f"변동 없음. 확인한 상품 수: {len(current)} (그중 품절: {soldout_count})")

    save_state(current)


if __name__ == "__main__":
    main()
