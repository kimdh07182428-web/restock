#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 브랜드스토어(포켓몬) 카드게임 카테고리 재입고 감지 스크립트 - v9
해시 클래스명 의존 제거, href 패턴 기반 파싱으로 변경.
GitHub Actions에서 5분마다 실행 -> 재입고 감지되면 ntfy.sh로 폰에 푸시 알림.
"""

import json
import os
import re
import sys
import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TARGET_URL = "https://m.brand.naver.com/pokemon/category/c94139abcef14362997090c5da975e28?st=POPULAR&dt=IMAGE&page=1"
BASE_URL = "https://m.brand.naver.com"
STATE_FILE = os.path.join(os.path.dirname(__file__), "state_naverstore.json")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "CHANGE_ME_TO_RANDOM_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

BLOCK_INDICATORS = ["에러페이지", "접속이 불가", "일시적으로 제한"]
PRODUCT_LINK_SELECTOR = "a[href*='/products/']"


def count_links(page) -> int:
    return page.eval_on_selector_all(PRODUCT_LINK_SELECTOR, "els => els.length")


def fetch_rendered_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
            ),
            viewport={"width": 390, "height": 844},
            locale="ko-KR",
            is_mobile=True,
            has_touch=True,
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        context.set_extra_http_headers({
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://m.naver.com/",
        })
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        initial_count = count_links(page)
        print(f"[진단] 초기 a[href*='/products/'] 개수: {initial_count}")

        prev_count = initial_count
        stable_rounds = 0
        scroll_count = 0
        for _ in range(100):
            # 카드가 아닌 빈 공간(화면 상단 근처)으로 커서를 옮긴 뒤 스크롤 -> 실수 클릭 방지
            page.mouse.move(195, 60)
            page.mouse.wheel(0, 2500)
            scroll_count += 1

            count = count_links(page)
            for _ in range(10):
                page.wait_for_timeout(1000)
                count = count_links(page)
                if count > prev_count:
                    break

            if count == prev_count:
                stable_rounds += 1
                if stable_rounds >= 5:
                    break
            else:
                stable_rounds = 0
            prev_count = count

        final_count = count_links(page)
        print(f"[정보] 스크롤 횟수: {scroll_count}")
        print(f"[정보] 최종 a[href*='/products/'] 개수: {final_count}")

        if final_count < initial_count:
            print("[경고] 최종 개수가 초기 개수보다 적음 -> 페이지 이동/초기화 의심")

        html = page.content()
        browser.close()
        return html


def is_blocked(html: str) -> bool:
    return any(kw in html for kw in BLOCK_INDICATORS)


def parse_products(html: str) -> dict:
    """href의 productNo를 기준으로 상품을 찾음 (해시 클래스명에 의존하지 않음)."""
    soup = BeautifulSoup(html, "lxml")
    links = soup.select(PRODUCT_LINK_SELECTOR)

    result = {}
    for link in links:
        href = link.get("href", "")
        m = re.search(r"/products/(\d+)", href)
        if not m:
            continue
        product_no = m.group(1)
        if product_no in result:
            continue

        # 이름: 링크 내부 이미지의 alt 속성 우선, 없으면 상위 요소의 텍스트 사용
        name = None
        img = link.select_one("img[alt]")
        if img and img.get("alt"):
            name = img.get("alt").strip()

        # 품절 여부 판단 및 이름 보완을 위해 상위 요소로 몇 단계 올라감
        card = link
        for _ in range(5):
            if card.parent is None:
                break
            card = card.parent

        if not name:
            text_candidates = card.find_all(string=True)
            for t in text_candidates:
                t_clean = t.strip()
                if t_clean and "품절" not in t_clean and len(t_clean) > 1:
                    name = t_clean
                    break
            if not name:
                name = f"상품 {product_no}"

        card_text = card.get_text(" ", strip=True)
        is_soldout = "품절" in card_text

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
    html = None
    for attempt in range(1, 4):
        try:
            candidate = fetch_rendered_html(TARGET_URL)
        except Exception as e:
            print(f"[시도 {attempt}] 렌더링 실패: {e}", file=sys.stderr)
            continue

        if is_blocked(candidate):
            print(f"[시도 {attempt}] 차단 페이지 감지됨. 재시도 대기...")
            time.sleep(5)
            continue

        html = candidate
        break

    if html is None:
        print("모든 시도에서 차단되거나 실패했습니다.", file=sys.stderr)
        return

    current = parse_products(html)
    if not current:
        print("상품을 하나도 못 찾았습니다. 사이트 구조가 바뀌었을 수 있습니다.")
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
