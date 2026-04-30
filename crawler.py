"""
대구 법원경매 자동 수집기 v10
=====================================
- 페이지네이션 개선 (11페이지 이후도 수집)
- 알림창(Alert) 자동 처리
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import UnexpectedAlertPresentException, NoAlertPresentException
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


def dismiss_alert(driver):
    """알림창 자동 닫기"""
    try:
        alert = driver.switch_to.alert
        log.info(f"알림창 닫기: {alert.text}")
        alert.accept()
        return True
    except NoAlertPresentException:
        return False


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


def set_daegu_filter(driver):
    """JavaScript로 대구광역시 필터 설정"""
    result = driver.execute_script("""
        var selects = document.querySelectorAll('select');
        var info = [];
        for(var sel of selects) {
            var name = sel.name || sel.id || '';
            var opts = Array.from(sel.options).map(o => ({v: o.value, t: o.text.trim()}));
            for(var opt of opts) {
                if(opt.t.includes('대구') || opt.v.includes('대구')) {
                    sel.value = opt.v;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    info.push('✅ ' + opt.v + ' in ' + name);
                    break;
                }
            }
        }
        return info;
    """)
    for line in (result or []):
        log.info(f"  {line}")
    return len(result or []) > 0


def collect_page(driver):
    """현재 페이지 결과 수집"""
    items = []
    dismiss_alert(driver)

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


def go_to_next_page(driver, current_page):
    """다음 페이지로 이동 — 여러 방식 시도"""

    # 방법 1: 다음 페이지 번호 링크
    try:
        next_num = driver.find_element(
            By.XPATH, f"//a[normalize-space(text())='{current_page + 1}']"
        )
        driver.execute_script("arguments[0].click();", next_num)
        time.sleep(3)
        dismiss_alert(driver)
        return True
    except:
        pass

    # 방법 2: 다음 버튼 (>, 다음, next)
    next_selectors = [
        "a.next",
        "a[title='다음페이지']",
        "a[title='다음']",
        ".paging_next a",
        "a[onclick*='next']",
        "img[alt='다음']",
    ]
    for selector in next_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, selector)
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(3)
                dismiss_alert(driver)
                return True
        except:
            continue

    # 방법 3: JS로 페이지 이동 함수 호출
    try:
        result = driver.execute_script(f"""
            // goPage, movePage, fnPage 등 함수 찾기
            var fns = ['goPage', 'movePage', 'fnPage', 'gotoPage', 'pageMove'];
            for(var fn of fns) {{
                if(typeof window[fn] === 'function') {{
                    window[fn]({current_page + 1});
                    return fn + '({current_page + 1}) 호출';
                }}
            }}
            return 'no-page-fn';
        """)
        log.info(f"JS 페이지 이동: {result}")
        if "no-page-fn" not in str(result):
            time.sleep(3)
            dismiss_alert(driver)
            return True
    except:
        pass

    return False


def run():
    log.info("=" * 50)
    log.info("대구 법원경매 수집 시작 v10")
    log.info(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    driver = get_driver()
    all_items = []

    try:
        # 메인 페이지 접속
        driver.get(f"{BASE_URL}/pgj/index.on")
        time.sleep(5)
        dismiss_alert(driver)

        # 부동산 버튼 클릭
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[value='부동산']")
            driver.execute_script("arguments[0].click();", btn)
            log.info("부동산 클릭")
            time.sleep(5)
            dismiss_alert(driver)
        except Exception as e:
            log.warning(f"부동산 버튼 실패: {e}")
            dismiss_alert(driver)

        # 대구 필터 설정
        log.info("대구 필터 설정...")
        set_daegu_filter(driver)
        time.sleep(2)

        # 검색하기 클릭
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[value='검색하기']")
            driver.execute_script("arguments[0].click();", btn)
            log.info("검색하기 클릭!")
            time.sleep(5)
            dismiss_alert(driver)
        except Exception as e:
            log.warning(f"검색 버튼 실패: {e}")

        log.info(f"검색 후 URL: {driver.current_url}")

        # ── 전체 페이지 수집 ──────────────────────────────
        page = 1
        consecutive_empty = 0

        while page <= 100:  # 최대 100페이지
            items = collect_page(driver)
            log.info(f"페이지 {page}: {len(items)}건")

            if items:
                all_items.extend(items)
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    log.info("빈 페이지 2회 연속 — 수집 완료")
                    break

            # 다음 페이지 이동
            moved = go_to_next_page(driver, page)
            if not moved:
                log.info(f"다음 페이지 없음 (현재: {page}페이지)")
                break
            page += 1

        # 대구 물건 필터
        daegu_items = [
            item for item in all_items
            if "대구" in item.get("address", "") or "대구" in item.get("court", "")
        ]
        log.info(f"전체: {len(all_items)}건 / 대구: {len(daegu_items)}건")
        final_items = daegu_items if daegu_items else all_items

    except Exception as e:
        log.error(f"전체 오류: {e}")
        final_items = all_items
    finally:
        driver.quit()

    log.info(f"\n✅ 총 {len(final_items)}건 수집 완료")

    if len(final_items) == 0:
        log.warning("수집 데이터 없음 — 기존 data.json 유지")
        return

    output = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(final_items),
        "items": final_items
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info(f"💾 저장 완료 ({len(final_items)}건)")


if __name__ == "__main__":
    run()
