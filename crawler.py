"""
대구 법원경매 자동 수집기 v7
=====================================
- select name: mf_sbx_rletRpdtCortLst 사용
- 대구 법원 옵션 텍스트로 선택
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
import json, time, re, logging
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


def get_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=ko-KR")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def parse_price(text):
    if not text:
        return 0
    text = re.sub(r'\s+', '', text).replace(',', '')
    total = 0
    if '억' in text:
        parts = text.split('억')
        total = int(re.sub(r'[^0-9]', '', parts[0]) or 0) * 10000
        if len(parts) > 1:
            r = re.sub(r'[^0-9]', '', parts[1].split('만')[0])
            total += int(r or 0)
    elif '만' in text:
        total = int(re.sub(r'[^0-9]', '', text.split('만')[0]) or 0)
    else:
        nums = re.sub(r'[^0-9]', '', text)
        if nums:
            val = int(nums)
            total = val // 10000 if val > 100000000 else val
    return total


def collect_all_pages(driver):
    """현재 검색 결과 전체 페이지 수집"""
    all_items = []
    page = 1

    while True:
        items = collect_page(driver)
        log.info(f"  페이지 {page}: {len(items)}건")
        if not items:
            break
        all_items.extend(items)

        # 다음 페이지 버튼 찾기
        try:
            next_btn = driver.find_element(
                By.CSS_SELECTOR,
                "a.next, .paging_next, a[title='다음페이지'], a[title='다음']"
            )
            driver.execute_script("arguments[0].click();", next_btn)
            time.sleep(3)
            page += 1
        except:
            # 페이지 번호로 시도
            try:
                next_num = driver.find_element(
                    By.XPATH,
                    f"//a[text()='{page+1}']"
                )
                driver.execute_script("arguments[0].click();", next_num)
                time.sleep(3)
                page += 1
            except:
                break

        if page > 50:  # 안전장치
            break

    return all_items


def collect_page(driver):
    """현재 페이지 결과 수집"""
    items = []
    tables = driver.find_elements(By.CSS_SELECTOR, "table")

    for table in tables:
        rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        if not rows:
            rows = table.find_elements(By.CSS_SELECTOR, "tr")[1:]

        for row in rows:
            try:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 5:
                    continue
                texts = [c.text.strip() for c in cols]
                case_no = texts[0]
                if not case_no or "타경" not in case_no:
                    continue

                address = texts[2] if len(texts) > 2 else ""
                appraisal = parse_price(texts[3]) if len(texts) > 3 else 0
                min_price = parse_price(texts[4]) if len(texts) > 4 else 0
                bid_date = texts[5] if len(texts) > 5 else ""
                discount = round((1 - min_price/appraisal)*100) if appraisal and min_price else 0

                # 법원명 추출
                court = texts[1] if len(texts) > 1 else ""

                detail_url = ""
                try:
                    link = cols[0].find_element(By.TAG_NAME, "a")
                    detail_url = link.get_attribute("href") or ""
                except:
                    pass

                items.append({
                    "case_no": case_no,
                    "court": court,
                    "address": address,
                    "apt_name": " ".join(address.split()[-2:]) if address else "",
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

    return items


def run():
    log.info("=" * 50)
    log.info("대구 법원경매 수집 시작 v7")
    log.info(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    driver = get_driver()
    all_items = []

    try:
        # 메인 페이지 접속
        driver.get(f"{BASE_URL}/pgj/index.on")
        time.sleep(4)

        # 부동산 버튼 클릭
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[value='부동산']")
            driver.execute_script("arguments[0].click();", btn)
            log.info("부동산 클릭")
            time.sleep(3)
        except Exception as e:
            log.warning(f"부동산 버튼 실패: {e}")

        # 법원 select 찾기 (name=mf_sbx_rletRpdtCortLst)
        try:
            sel_el = driver.find_element(
                By.CSS_SELECTOR,
                "select[name='mf_sbx_rletRpdtCortLst']"
            )
            sel = Select(sel_el)

            # 전체 옵션 출력
            all_opts = [(o.get_attribute("value"), o.text.strip()) for o in sel.options]
            log.info(f"법원 옵션 전체: {all_opts}")

            # 대구 관련 옵션 찾기
            daegu_opts = [(v, t) for v, t in all_opts if "대구" in t]
            log.info(f"대구 관련 옵션: {daegu_opts}")

            if daegu_opts:
                # 첫 번째 대구 옵션 선택
                val, txt = daegu_opts[0]
                sel.select_by_value(val)
                log.info(f"대구 법원 선택: {txt} ({val})")
                time.sleep(1)
            else:
                log.warning("대구 옵션 없음 - 전체 검색으로 진행")

        except Exception as e:
            log.warning(f"법원 select 오류: {e}")

        # 검색하기 클릭
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[value='검색하기']")
            driver.execute_script("arguments[0].click();", btn)
            log.info("검색하기 클릭!")
            time.sleep(5)
        except Exception as e:
            log.warning(f"검색 버튼 실패: {e}")

        log.info(f"검색 후 URL: {driver.current_url}")

        # 결과 수집
        items = collect_all_pages(driver)
        log.info(f"수집 완료: {len(items)}건")

        # 대구 물건만 필터
        daegu_items = [
            item for item in items
            if "대구" in item.get("address", "") or "대구" in item.get("court", "")
        ]
        log.info(f"대구 물건 필터: {len(daegu_items)}건")

        all_items = daegu_items if daegu_items else items

    except Exception as e:
        log.error(f"전체 오류: {e}")
    finally:
        driver.quit()

    log.info(f"\n✅ 총 {len(all_items)}건 수집 완료")

    if len(all_items) == 0:
        log.warning("수집 데이터 없음 — 기존 data.json 유지")
        return

    output = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(all_items),
        "items": all_items
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info(f"💾 저장 완료 ({len(all_items)}건)")


if __name__ == "__main__":
    run()
