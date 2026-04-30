"""
대구 법원경매 자동 수집기 v6
=====================================
- 법원 select 상세 분석
- 검색 후 메인 페이지에서 결과 수집
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


def collect_results(driver):
    """현재 페이지에서 경매 결과 수집"""
    items = []
    tables = driver.find_elements(By.CSS_SELECTOR, "table")
    log.info(f"테이블 수: {len(tables)}")

    for i, table in enumerate(tables):
        rows = table.find_elements(By.CSS_SELECTOR, "tr")
        if len(rows) < 2:
            continue

        # 헤더 확인
        header = rows[0].find_elements(By.CSS_SELECTOR, "th, td")
        header_texts = [h.text.strip() for h in header]
        log.info(f"테이블[{i}] 헤더: {header_texts}")

        # 데이터 행 수집
        for row in rows[1:]:
            try:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 4:
                    continue
                texts = [c.text.strip() for c in cols]
                case_no = texts[0]
                if not case_no or "타경" not in case_no:
                    continue

                log.info(f"  물건: {texts[:6]}")
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
                    "court": "",
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
    log.info("대구 법원경매 수집 시작 v6")
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
            log.info("부동산 버튼 클릭")
            time.sleep(3)
        except Exception as e:
            log.warning(f"부동산 버튼 실패: {e}")

        # ── select 전체 분석 (법원 코드 찾기) ──────────
        selects = driver.find_elements(By.TAG_NAME, "select")
        log.info(f"select 수: {len(selects)}")

        court_select_el = None
        for sel_el in selects:
            try:
                name = sel_el.get_attribute("name") or sel_el.get_attribute("id") or ""
                sel = Select(sel_el)
                options = [(o.get_attribute("value"), o.text.strip()) for o in sel.options]
                log.info(f"select[{name}]: {options[:5]}")

                # 대구 법원 코드가 있는지 확인
                vals = [o[0] for o in options]
                if "B30G0000" in vals or any("대구" in o[1] for o in options):
                    log.info(f"  ✅ 법원 select 발견! name={name}")
                    court_select_el = sel_el
                    break
            except:
                continue

        # 대구 전체 선택 (법원 코드 직접 설정)
        if court_select_el:
            try:
                sel = Select(court_select_el)
                # 대구 관련 옵션 찾기
                for opt in sel.options:
                    val = opt.get_attribute("value") or ""
                    txt = opt.text.strip()
                    if "대구" in txt or val == "B30G0000":
                        sel.select_by_value(val)
                        log.info(f"법원 선택: {txt} ({val})")
                        time.sleep(1)
                        break
            except Exception as e:
                log.warning(f"법원 선택 실패: {e}")
        else:
            # JavaScript로 직접 값 설정 시도
            result = driver.execute_script("""
                var selects = document.querySelectorAll('select');
                var info = [];
                for(var sel of selects) {
                    var name = sel.name || sel.id || '';
                    var opts = Array.from(sel.options).map(o => o.value + ':' + o.text);
                    info.push(name + ' => ' + opts.slice(0,3).join(', '));
                    
                    // 대구 법원 코드 설정 시도
                    if(opts.some(o => o.includes('B30G') || o.includes('대구'))) {
                        sel.value = 'B30G0000';
                        sel.dispatchEvent(new Event('change'));
                        info.push('대구 선택 시도!');
                    }
                }
                return info;
            """)
            log.info(f"JS select 결과: {result}")
            time.sleep(1)

        # 검색하기 클릭
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[value='검색하기']")
            driver.execute_script("arguments[0].click();", btn)
            log.info("검색하기 클릭!")
            time.sleep(5)
        except Exception as e:
            log.warning(f"검색하기 실패: {e}")

        # 현재 URL 및 페이지 확인
        log.info(f"검색 후 URL: {driver.current_url}")
        log.info(f"검색 후 타이틀: {driver.title}")

        # 메인 페이지 결과 수집
        items = collect_results(driver)
        log.info(f"메인 페이지 수집: {len(items)}건")
        all_items.extend(items)

        # 다음 페이지 수집
        page = 2
        while page <= 20:
            try:
                next_btn = driver.find_element(
                    By.XPATH,
                    f"//a[contains(@onclick,'{page}') or text()='{page}']"
                )
                driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(3)
                new_items = collect_results(driver)
                if not new_items:
                    break
                all_items.extend(new_items)
                log.info(f"페이지 {page}: {len(new_items)}건")
                page += 1
            except:
                break

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
