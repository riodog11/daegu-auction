"""
대구 법원경매 자동 수집기 (Selenium 버전)
==========================================
실제 브라우저처럼 동작해서 대법원 경매 사이트에서
대구 지역 경매 물건을 자동으로 수집합니다.
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
import json
import time
import re
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crawler.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

BASE_URL = "https://www.courtauction.go.kr"
DATA_FILE = "data.json"

DAEGU_COURTS = {
    "B30G0000": "대구지방법원",
    "B30B0000": "대구지방법원 경주지원",
    "B30C0000": "대구지방법원 김천지원",
    "B30D0000": "대구지방법원 안동지원",
    "B30E0000": "대구지방법원 상주지원",
    "B30F0000": "대구지방법원 의성지원",
    "B30H0000": "대구지방법원 영덕지원",
    "B30I0000": "대구지방법원 포항지원",
}


def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def parse_price(text):
    if not text:
        return 0
    text = text.replace(",", "").replace(" ", "").strip()
    total = 0
    if "억" in text:
        parts = text.split("억")
        total = int(re.sub(r"[^0-9]", "", parts[0]) or 0) * 10000
        if len(parts) > 1 and parts[1]:
            나머지 = re.sub(r"[^0-9]", "", parts[1].split("만")[0])
            total += int(나머지 or 0)
    elif "만" in text:
        total = int(re.sub(r"[^0-9]", "", text.split("만")[0]) or 0)
    else:
        nums = re.sub(r"[^0-9]", "", text)
        if nums:
            val = int(nums)
            total = val // 10000 if val > 10000 else val
    return total


def crawl_list(driver):
    """대구 전체 경매 목록 수집"""
    items = []
    wait = WebDriverWait(driver, 20)

    try:
        # 물건검색 페이지 직접 접속
        driver.get(f"{BASE_URL}/pgj/index.on")
        time.sleep(3)

        # 페이지 소스 확인
        page_source = driver.page_source
        log.info(f"페이지 로드 완료 (길이: {len(page_source)})")

        # 법원 드롭다운 찾기
        selects = driver.find_elements(By.TAG_NAME, "select")
        log.info(f"select 요소 {len(selects)}개 발견")

        for court_code, court_name in DAEGU_COURTS.items():
            log.info(f"\n📍 {court_name} 수집 중...")
            try:
                # 법원 선택
                for sel in selects:
                    try:
                        s = Select(sel)
                        options = [o.get_attribute("value") for o in s.options]
                        if court_code in options:
                            s.select_by_value(court_code)
                            time.sleep(1)
                            log.info(f"  법원 선택 완료: {court_name}")
                            break
                    except:
                        continue

                # 검색 실행
                try:
                    btn = driver.find_element(
                        By.CSS_SELECTOR,
                        "input[type='button'][value='검색'], "
                        "input[type='submit'], "
                        "button.btn_search, "
                        "a.btn_search"
                    )
                    btn.click()
                    time.sleep(3)
                except Exception as e:
                    log.warning(f"  검색 버튼 오류: {e}")
                    continue

                # 결과 수집
                page = 1
                while True:
                    rows = driver.find_elements(
                        By.CSS_SELECTOR,
                        "table tbody tr"
                    )
                    log.info(f"  페이지 {page}: {len(rows)}건")

                    for row in rows:
                        try:
                            cols = row.find_elements(By.TAG_NAME, "td")
                            if len(cols) < 5:
                                continue

                            case_no = cols[0].text.strip()
                            if not case_no or "타경" not in case_no:
                                continue

                            address = cols[2].text.strip() if len(cols) > 2 else ""
                            appraisal = parse_price(cols[3].text if len(cols) > 3 else "")
                            min_price = parse_price(cols[4].text if len(cols) > 4 else "")
                            bid_date = cols[5].text.strip() if len(cols) > 5 else ""
                            discount = round((1 - min_price / appraisal) * 100) if appraisal and min_price else 0

                            detail_url = ""
                            try:
                                link = cols[0].find_element(By.TAG_NAME, "a")
                                detail_url = link.get_attribute("href") or ""
                            except:
                                pass

                            items.append({
                                "case_no": case_no,
                                "court": court_name,
                                "address": address,
                                "apt_name": address.split()[-2] if address else "",
                                "area": "",
                                "floor": "",
                                "direction": "",
                                "item_type": "아파트",
                                "appraisal": appraisal,
                                "min_price": min_price,
                                "discount": discount,
                                "bid_date": bid_date,
                                "status": "진행",
                                "lat": 35.8714,
                                "lng": 128.6014,
                                "documents": [],
                                "detail_url": detail_url,
                                "blog_url": ""
                            })
                        except:
                            continue

                    # 다음 페이지
                    try:
                        next_btn = driver.find_element(
                            By.CSS_SELECTOR, "a.next, .paging a:last-child"
                        )
                        if "disabled" not in next_btn.get_attribute("class"):
                            next_btn.click()
                            time.sleep(2)
                            page += 1
                        else:
                            break
                    except:
                        break

            except Exception as e:
                log.error(f"  {court_name} 오류: {e}")
                continue

    except Exception as e:
        log.error(f"크롤링 오류: {e}")

    return items


def run():
    log.info("=" * 50)
    log.info("대구 법원경매 수집 시작 (Selenium)")
    log.info(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    driver = get_driver()
    all_items = []

    try:
        all_items = crawl_list(driver)
    finally:
        driver.quit()

    log.info(f"\n✅ 총 {len(all_items)}건 수집 완료")

    if len(all_items) == 0:
        log.warning("수집된 데이터가 없어 기존 data.json 유지")
        return

    output = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(all_items),
        "items": all_items
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info(f"💾 data.json 저장 완료 ({len(all_items)}건)")


if __name__ == "__main__":
    run()
