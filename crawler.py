"""
대구 법원경매 자동 수집기 v5
=====================================
iframe 구조 + "검색하기" 버튼 방식
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
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


def switch_to_search_frame(driver):
    """검색 폼이 있는 iframe으로 전환"""
    # 메인 프레임으로
    driver.switch_to.default_content()

    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    log.info(f"iframe 수: {len(iframes)}")

    for i, iframe in enumerate(iframes):
        src = iframe.get_attribute("src") or ""
        name = iframe.get_attribute("name") or iframe.get_attribute("id") or ""
        log.info(f"  iframe[{i}]: name={name} src={src[:80]}")

    # iframe 순서대로 검색 폼 찾기
    for i, iframe in enumerate(iframes):
        try:
            driver.switch_to.frame(iframe)
            forms = driver.find_elements(By.TAG_NAME, "form")
            selects = driver.find_elements(By.TAG_NAME, "select")
            if forms or len(selects) > 2:
                log.info(f"iframe[{i}]에서 폼 발견! forms={len(forms)} selects={len(selects)}")
                return True
            driver.switch_to.default_content()
        except:
            driver.switch_to.default_content()
            continue

    log.warning("검색 폼 iframe 못 찾음")
    return False


def crawl_court(driver, court_code, court_name):
    items = []
    wait = WebDriverWait(driver, 15)

    try:
        # 메인 페이지 접속
        driver.get(f"{BASE_URL}/pgj/index.on")
        time.sleep(4)
        driver.switch_to.default_content()

        # "부동산" 버튼 먼저 클릭 (메인 메뉴)
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[value='부동산']")
            driver.execute_script("arguments[0].click();", btn)
            log.info("부동산 버튼 클릭")
            time.sleep(3)
        except Exception as e:
            log.warning(f"부동산 버튼 클릭 실패: {e}")

        # iframe으로 전환
        switched = switch_to_search_frame(driver)

        if not switched:
            # iframe 없이 직접 시도
            driver.switch_to.default_content()

        # 현재 컨텍스트에서 법원 select 찾기
        selects = driver.find_elements(By.TAG_NAME, "select")
        log.info(f"현재 컨텍스트 select 수: {len(selects)}")

        for sel_el in selects:
            try:
                name = sel_el.get_attribute("name") or ""
                sel = Select(sel_el)
                options_vals = [o.get_attribute("value") for o in sel.options]
                if court_code in options_vals:
                    sel.select_by_value(court_code)
                    log.info(f"법원 선택 성공: {court_name} (select name={name})")
                    time.sleep(1)
                    break
            except:
                continue

        # "검색하기" 버튼 클릭
        search_clicked = False
        search_selectors = [
            "input[value='검색하기']",
            "input[value='검색']",
            "input[value='조회']",
            "button[type='submit']",
            "input[type='submit']",
        ]

        for selector in search_selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, selector)
                driver.execute_script("arguments[0].click();", btn)
                log.info(f"검색 버튼 클릭 성공: {selector}")
                search_clicked = True
                time.sleep(4)
                break
            except:
                continue

        if not search_clicked:
            # JS로 검색하기 버튼 찾아서 클릭
            result = driver.execute_script("""
                var inputs = document.querySelectorAll('input, button');
                for(var el of inputs) {
                    var val = (el.value || el.textContent || '').trim();
                    if(val === '검색하기' || val === '검색' || val === '조회') {
                        el.click();
                        return '클릭: ' + val;
                    }
                }
                // 모든 iframe 안도 검색
                var frames = document.querySelectorAll('iframe');
                return '버튼없음 (iframe수:' + frames.length + ')';
            """)
            log.info(f"JS 검색 결과: {result}")
            time.sleep(4)

        # 결과 iframe으로 전환해서 테이블 수집
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.TAG_NAME, "iframe")

        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
                if len(rows) > 1:
                    log.info(f"결과 테이블 발견: {len(rows)}행")

                    for row in rows:
                        try:
                            cols = row.find_elements(By.TAG_NAME, "td")
                            if len(cols) < 5:
                                continue

                            texts = [c.text.strip() for c in cols]
                            case_no = texts[0]

                            if not case_no or "타경" not in case_no:
                                continue

                            log.info(f"물건: {texts[:5]}")

                            address = texts[2] if len(texts) > 2 else ""
                            appraisal = parse_price(texts[3]) if len(texts) > 3 else 0
                            min_price = parse_price(texts[4]) if len(texts) > 4 else 0
                            bid_date = texts[5] if len(texts) > 5 else ""
                            discount = round((1 - min_price/appraisal)*100) if appraisal and min_price else 0

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

                driver.switch_to.default_content()
                if items:
                    break
            except:
                driver.switch_to.default_content()
                continue

    except Exception as e:
        log.error(f"오류: {e}")
        driver.switch_to.default_content()

    log.info(f"{court_name}: {len(items)}건 수집")
    return items


def run():
    log.info("=" * 50)
    log.info("대구 법원경매 수집 시작 v5")
    log.info(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    driver = get_driver()
    all_items = []

    try:
        for court_code, court_name in DAEGU_COURTS.items():
            items = crawl_court(driver, court_code, court_name)
            all_items.extend(items)
            time.sleep(2)
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
