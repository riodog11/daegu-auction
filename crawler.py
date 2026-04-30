"""
대구 법원경매 자동 수집기 v4
=====================================
JavaScript 직접 실행 방식으로 검색
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

# 대구 법원 코드
DAEGU_COURTS = {
    "B30G0000": "대구지방법원",
    "B30B0000": "대구지방법원 경주지원",
    "B30C0000": "대구지방법원 김천지원",
    "B30D0000": "대구지방법원 안동지원",
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


def analyze_page(driver):
    """페이지 구조 상세 분석"""
    log.info("=== 페이지 구조 분석 ===")
    log.info(f"URL: {driver.current_url}")
    log.info(f"Title: {driver.title}")

    # 모든 폼
    forms = driver.find_elements(By.TAG_NAME, "form")
    log.info(f"폼 수: {len(forms)}")
    for i, form in enumerate(forms):
        action = form.get_attribute("action") or ""
        method = form.get_attribute("method") or ""
        log.info(f"  폼[{i}]: action={action} method={method}")

    # 모든 버튼/인풋
    els = driver.find_elements(By.CSS_SELECTOR, "button, input[type='button'], input[type='submit'], input[type='image']")
    log.info(f"버튼 수: {len(els)}")
    for el in els:
        tag = el.tag_name
        val = el.get_attribute("value") or el.text or ""
        onclick = el.get_attribute("onclick") or ""
        name = el.get_attribute("name") or ""
        log.info(f"  버튼: tag={tag} val={val} name={name} onclick={onclick[:80]}")

    # onclick 있는 링크
    links = driver.find_elements(By.CSS_SELECTOR, "a[onclick]")
    log.info(f"onclick 링크 수: {len(links)}")
    for link in links[:20]:
        txt = link.text.strip() or link.get_attribute("title") or ""
        onclick = link.get_attribute("onclick") or ""
        log.info(f"  링크: [{txt}] onclick={onclick[:100]}")

    # select 상세
    selects = driver.find_elements(By.TAG_NAME, "select")
    log.info(f"select 수: {len(selects)}")
    for sel in selects:
        name = sel.get_attribute("name") or sel.get_attribute("id") or ""
        options = [f"{o.get_attribute('value')}:{o.text.strip()}" for o in sel.find_elements(By.TAG_NAME, "option")]
        log.info(f"  select name={name}: {options[:8]}")

    log.info("=== 분석 완료 ===")


def try_search(driver, court_code, court_name):
    """다양한 방법으로 검색 시도"""
    items = []
    wait = WebDriverWait(driver, 15)

    log.info(f"\n{'='*40}")
    log.info(f"법원: {court_name} ({court_code})")

    try:
        # 검색 페이지 접속
        driver.get(f"{BASE_URL}/pgj/index.on")
        time.sleep(3)

        # 페이지 분석 (첫 번째 법원만)
        if court_code == "B30G0000":
            analyze_page(driver)

        # select에서 법원 선택 시도
        selects = driver.find_elements(By.TAG_NAME, "select")
        for sel_el in selects:
            try:
                sel = Select(sel_el)
                values = [o.get_attribute("value") for o in sel.options]
                if court_code in values:
                    sel.select_by_value(court_code)
                    log.info(f"법원 선택 성공: {court_name}")
                    time.sleep(1)
                    break
            except:
                continue

        # 방법 1: JavaScript로 폼 직접 submit
        try:
            result = driver.execute_script("""
                var forms = document.querySelectorAll('form');
                for(var f of forms) {
                    f.submit();
                    return 'submit: ' + (f.action || 'no-action');
                }
                return 'no-form';
            """)
            log.info(f"JS 폼 submit 결과: {result}")
            time.sleep(3)
        except Exception as e:
            log.warning(f"JS 폼 submit 실패: {e}")

        # 방법 2: onclick 함수 직접 호출
        try:
            result = driver.execute_script("""
                // 검색 관련 함수 찾기
                var fns = Object.keys(window).filter(k => 
                    typeof window[k] === 'function' && 
                    (k.toLowerCase().includes('search') || 
                     k.toLowerCase().includes('srch') ||
                     k.toLowerCase().includes('list'))
                );
                return fns.slice(0, 10);
            """)
            log.info(f"검색 관련 함수: {result}")

            # 함수 직접 호출 시도
            for fn in (result or []):
                try:
                    driver.execute_script(f"window['{fn}']();")
                    log.info(f"함수 호출: {fn}()")
                    time.sleep(2)
                    break
                except:
                    continue
        except Exception as e:
            log.warning(f"JS 함수 호출 실패: {e}")

        # 방법 3: 버튼 JavaScript 클릭
        try:
            result = driver.execute_script("""
                var btns = document.querySelectorAll('button, input[type=button], input[type=submit], a');
                var found = null;
                for(var btn of btns) {
                    var txt = (btn.value || btn.textContent || btn.title || '').trim();
                    if(txt.includes('검색') || txt.includes('조회')) {
                        btn.click();
                        found = txt;
                        break;
                    }
                }
                return found || 'not found';
            """)
            log.info(f"JS 클릭 결과: {result}")
            time.sleep(3)
        except Exception as e:
            log.warning(f"JS 클릭 실패: {e}")

        # 결과 테이블 수집
        log.info(f"결과 URL: {driver.current_url}")
        tables = driver.find_elements(By.TAG_NAME, "table")
        log.info(f"테이블 수: {len(tables)}")

        for table in tables:
            rows = table.find_elements(By.TAG_NAME, "tr")
            if len(rows) < 2:
                continue

            log.info(f"테이블 행 수: {len(rows)}")
            # 헤더 확인
            header_cols = rows[0].find_elements(By.CSS_SELECTOR, "th, td")
            headers = [c.text.strip() for c in header_cols]
            log.info(f"헤더: {headers}")

            for row in rows[1:]:
                try:
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if len(cols) < 4:
                        continue

                    texts = [c.text.strip() for c in cols]
                    case_no = texts[0]

                    if not case_no or "타경" not in case_no:
                        continue

                    log.info(f"물건 발견: {texts[:6]}")

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

    except Exception as e:
        log.error(f"오류: {e}")

    log.info(f"수집 결과: {len(items)}건")
    return items


def run():
    log.info("=" * 50)
    log.info("대구 법원경매 수집 시작 v4")
    log.info(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    driver = get_driver()
    all_items = []

    try:
        for court_code, court_name in DAEGU_COURTS.items():
            items = try_search(driver, court_code, court_name)
            all_items.extend(items)
            time.sleep(1)
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
