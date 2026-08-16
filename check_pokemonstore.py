#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
포켓몬 스토어(pokemonstore.co.kr) 재입고 감지 스크립트 - 최종본 v3
'더보기' 버튼을 더 이상 없을 때까지 자동 클릭해서 카테고리 내 전체 상품을 수집.
GitHub Actions에서 5분마다 실행 -> 재입고 감지되면 ntfy.sh로 폰에 푸시 알림.
"""

import json
import os
import re
import sys

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TARGET_URL = "https://m.pokemonstore.co.kr/pages/product/product-list.html?categoryNo=488339"
BASE_URL = "https://m.pokemonstore.co.kr"
STATE_FILE = os.path.join(os.path.dirname(__file__), "state_pokemonstore.json")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "CHANGE_ME_TO_RANDOM_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"


def fetch_rendered_html(url: str) -> str:
    """Playwright로 페이지를 열고, '더보기' 버튼을 더 이상 없을 때까지 계속 클릭해서 전체 로딩."""
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
        page.wait_for_timeout(2000)

        click_count = 0
        for _ in range(50):  # 안전장치: 최대 50번 클릭
            more_button = page.locator("text=더보기").first
            try:
                if more_button.count() == 0 or not more_button.is_visible():
                    break
                before = page.eval_on_selector_all("a.thumb-item", "els => els.length")
                more_button.click()
                click_count += 1
                page.wait_for_timeout(1500)
                after = page.eval_on_selector_all("a.thumb-item", "els => els.length")
                if after == before:
                    break  # 클릭했는데 개수가 그대로면 더 로딩할 게 없는 것
            except Exception:
                break

        print(f"[정보] '더보기' 버튼 클릭 횟수: {click_count}")
        html = page.content()
        browser.close()
        return html


def parse_products(html: str) -> dict:
    """productNo -> {"name": str, "soldout": bool, "url": str} 딕셔너리 반환."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("a.thumb-item")

    result = {}
    for card in cards:
        href = card.get("href", "")
        m = re.search(r"productNo=(\d+)", href)
        if not m:
            continue
        product_no = m.group(1)

        title_tag = card.select_one("p.product-thumb-title")
        name = title_tag.get_text(strip=True) if title_tag else f"상품 {product_no}"

        is_soldout = card.select_one(".thumb-item__overlay") is not None

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
        print("[경고] NTFY_TOPIC이 기본값입니다. 실제 토픽명으로 바꿔주세요.", file=sys.stderr)

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
    last_error = None
    for attempt in range(1, 3):
        try:
            html = fetch_rendered_html(TARGET_URL)
            break
        except Exception as e:
            last_error = e
            print(f"[시도 {attempt}] 페이지 렌더링 실패: {e}", file=sys.stderr)

    if html is None:
        print(f"모든 재시도 실패. 마지막 에러: {last_error}", file=sys.stderr)
        return

    current = parse_products(html)
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
            notify("포켓몬 스토어 재입고!", item["name"], click_url=item["url"])
            print(f"재입고 감지 -> 알림 전송: {item['name']} ({item['url']})")
    else:
        soldout_count = sum(1 for v in current.values() if v["soldout"])
        print(f"변동 없음. 확인한 상품 수: {len(current)} (그중 품절: {soldout_count})")

    save_state(current)


if __name__ == "__main__":
    main()
