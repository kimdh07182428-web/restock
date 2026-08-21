#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 브랜드스토어(포켓몬) 카드게임 카테고리 재입고 감지 스크립트 - v8 (진단용)
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
INTERSTITIAL_HINTS = ["앱으로 보기", "네이버 앱에서 보기", "app-banner", "app_banner"]


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

        # 앱 유도 배너/인터스티셜이 있으면 텍스트로 감지해서 로그 남김
        first_html = page.content()
        for hint in INTERSTITIAL_HINTS:
            if hint in first_html:
                print(f"[진단] 앱 유도 배너 의심 텍스트 발견: '{hint}'")

        # 초기 상품 카드 수 (선택자별로 체크)
        count_hz4 = page.eval_on_selector_all("li.Hz4XxKbt9h", "els => els.length")
        count_any_product_link = page.eval_on_selector_all("a[href*='/products/']", "els => els.length")
        print(f"[진단] 초기 li.Hz4XxKbt9h 개수: {count_hz4}")
        print(f"[진단] 초기 a[href*='/products/'] 개수: {count_any_product_link}")

        # 실제 터치 스와이프 제스처로 스크롤 (synthetic scrollTo 대신)
        prev_count = count_hz4 if count_hz4 > 0 else count_any_product_link
        stable_rounds = 0
        scroll_count = 0
        for _ in range(100):
            try:
                page.touchscreen.tap(195, 700)
            except Exception:
                pass
            page.mouse.move(195, 700)
            page.mouse.wheel(0, 2500)
            scroll_count += 1

            count = max(
                page.eval_on_selector_all("li.Hz4XxKbt9h", "els => els.length"),
                page.eval_on_selector_all("a[href*='/products/']", "els => els.length"),
            )
            for _ in range(10):
                page.wait_for_timeout(1000)
                count = max(
                    page.eval_on_selector_all("li.Hz4XxKbt9h", "els => els.length"),
                    page.eval_on_selector_all("a[href*='/products/']", "els => els.length"),
                )
                if count > prev_count:
                    break

            if count == prev_count:
                stable_rounds += 1
                if stable_rounds >= 5:
                    break
            else:
                stable_rounds = 0
            prev_count = count

        print(f"[정보] 스크롤 횟수: {scroll_count}")
        print(f"[정보] 최종 li.Hz4XxKbt9h 개수: {page.eval_on_selector_all('li.Hz4XxKbt9h', 'els => els.length')}")
        print(f"[정보] 최종 a[href*='/products/'] 개수: {page.eval_on_selector_all(chr(39)+'a[href*=\"/products/\"]'+chr(39), 'els => els.length') if False else page.eval_on_selector_all('a[href*=\"/products/\"]', 'els => els.length')}")

        html = page.content()

        # 진단: li.Hz4XxKbt9h가 0인데 상품 링크는 있는 경우, 실제 부모 태그/클래스 샘플 출력
        if page.eval_on_selector_all("li.Hz4XxKbt9h", "els => els.length") == 0 and count_any_product_link > 0:
            sample = page.eval_on_selector(
                "a[href*='/products/']",
                "el => { let p = el; for (let i=0;i<4 && p;i++){p=p.parentElement;} return p ? p.outerHTML.slice(0,300) : 'NONE'; }"
            )
            print(f"[진단] 상품 링크의 상위 4단계 부모 HTML 샘플:\n{sample}")

        browser.close()
        return html


def is_blocked(html: str) -> bool:
    return any(kw in html for kw in BLOCK_INDICATORS)


def parse_products(html: str) -> dict:
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
