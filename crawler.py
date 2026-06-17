"""
대구 법원경매 자동 수집기 v13
=====================================
- 대구지방법원 + 대구서부지원 둘 다 수집
- 누적 저장 방식 (기존 데이터 유지하면서 신규 추가)
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoAlertPresentException
import json, time, re, logging, os
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

# 대구 법원 목록
DAEGU_COURTS = ["대구지방법원", "대구서부지원", "대구지방법원 서부지원"]


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
    try:
        alert = driver.switch_to.alert
        log.info(f"알림창 닫기: {alert.text}")
        alert.accept()
    except NoAlertPresentException:
        pass


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


def setup_filters(driver, court_name=None):
    """대구 + 특정 법원 필터 설정"""
    result = driver.execute_script("""
        var courtName = arguments[0];
        var selects = document.querySelectorAll('select');
        var info = [];

        for(var sel of selects) {
            var name = sel.name || sel.id || '';
            var opts = Array.from(sel.options).map(o => ({v: o.value, t: o.text.trim()}));

            // 시/도 → 대구광역시
            var hasSido = opts.some(o => o.t.includes('부산') || o.t.includes('인천') || o.t.includes('광주'));
            if(hasSido) {
                var daeguOpt = opts.find(o => o.t.includes('대구'));
                if(daeguOpt) {
                    sel.value = daeguOpt.v;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    info.push('✅ 시/도: ' + daeguOpt.t + ' (' + name + ')');
                }
            }

            // 법원 → 특정 법원 선택
            if(courtName) {
                var courtOpt = opts.find(o => o.t.includes(courtName));
                if(courtOpt && name.includes('Cort')) {
                    sel.value = courtOpt.v;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    info.push('✅ 법원: ' + courtOpt.t + ' (' + name + ')');
                }
            }
        }
        return info;
    """, court_name)

    for line in (result or []):
        log.info(f"  {line}")
    time.sleep(1)


def collect_page(driver, court_name):
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
                log.info(f"칼럼 확인: {texts}")
                address = texts[2] if len(texts) > 2 else ""
                appraisal = parse_price(texts[3]) if len(texts) > 3 else 0
                min_price = parse_price(texts[4]) if len(texts) > 4 else 0
                bid_date = texts[5] if len(texts) > 5 else ""
                discount = round((1 - min_price/appraisal)*100) if appraisal and min_price else 0
                court = texts[1] if len(texts) > 1 else court_name
                detail_url = ""
                try:
                    link = cols[0].find_element(By.TAG_NAME, "a")
                    detail_url = link.get_attribute("href") or ""
                except:
                    pass
                items.append({
                    "case_no": case_no,
                    "court": court or court_name,
                    "address": address,
                    "apt_name": " ".join(address.split()[-2:]) if address else "",
                    "area": "", "floor": "", "direction": "",
                    "item_type": "아파트",
                    "appraisal": appraisal,
                    "min_price": min_price,
                    "discount": discount,
                    "bid_date": bid_date,
                    "status": "진행",
                    "lat": 35.8714, "lng": 128.6014,
                    "documents": [],
                    "detail_url": detail_url,
                    "blog_url": "",
                    "collected_at": datetime.now().strftime("%Y-%m-%d")
                })
            except:
                continue
    return items


def go_next_page(driver, current_page):
    # 방법 1: 다음 페이지 번호 클릭
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

    # 방법 2: '다음 목록' 버튼 (10페이지 묶음 이후 핵심!)
    for selector in [
        "button.w2pageList_col_next",
        "button[title='다음 목록']",
        ".w2pageList_col_next",
        "a[title='다음페이지']",
        "a.next",
        "a[title='다음']",
    ]:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, selector)
            if btn.is_displayed() and btn.is_enabled():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(3)
                dismiss_alert(driver)
                return True
        except:
            continue
    return False



def crawl_court(driver, court_name, page_type="PGJ151F00"):
    """특정 법원 전체 수집
    page_type: PGJ151F00=물건상세검색(2주치), PGJ157M00=매각예정물건(6주치)
    """
    log.info(f"법원: {court_name} / 유형: {page_type}")

    all_items = []

    # 페이지 접속
    url = f"{BASE_URL}/pgj/index.on?w2xPath=/pgj/ui/pgj100/{page_type}.xml"
    driver.get(url)
    time.sleep(5)
    dismiss_alert(driver)
    log.info(f"접속 완료")

    # 필터 설정
    setup_filters(driver, court_name)

    # 검색
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "input[value='검색하기']")
        driver.execute_script("arguments[0].click();", btn)
        log.info("검색 실행!")
        time.sleep(5)
        dismiss_alert(driver)
    except Exception as e:
        log.warning(f"검색 실패: {e}")

    # 페이지 수집
    page = 1
    prev_case_nos = set()

    while page <= 200:
        items = collect_page(driver, court_name)
        log.info(f"  페이지 {page}: {len(items)}건")

        if not items:
            break

        current_case_nos = {item["case_no"] for item in items}
        if current_case_nos == prev_case_nos:
            log.info("  중복 페이지 — 종료")
            break
        prev_case_nos = current_case_nos
        all_items.extend(items)

        if not go_next_page(driver, page):
            break
        page += 1

    log.info(f"{court_name} 수집 완료: {len(all_items)}건")
    return all_items


def load_existing_data():
    """기존 data.json 불러오기"""
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        existing = {item["case_no"]: item for item in data.get("items", [])}
        log.info(f"기존 데이터 로드: {len(existing)}건")
        return existing
    except:
        return {}


def merge_data(existing, new_items):
    """기존 데이터에 신규 데이터 병합 (누적)"""
    added = 0
    updated = 0

    for item in new_items:
        case_no = item["case_no"]
        if case_no not in existing:
            existing[case_no] = item
            added += 1
        else:
            # 기존 데이터 업데이트 (blog_url 유지)
            blog_url = existing[case_no].get("blog_url", "")
            existing[case_no] = item
            existing[case_no]["blog_url"] = blog_url
            updated += 1

    log.info(f"병합 결과: 신규 {added}건 추가 / {updated}건 업데이트")
    return existing


def run():
    log.info("=" * 50)
    log.info("대구 법원경매 수집 시작 v13 (누적 저장)")
    log.info(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    # 기존 데이터 로드
    existing_data = load_existing_data()

    driver = get_driver()
    new_items = []

    try:
        # ── 1. 물건상세검색 (오늘 ~ 2주치) ──────────────
        log.info("\n[1단계] 물건상세검색 수집 시작")
        items1 = crawl_court(driver, "대구지방법원", "PGJ151F00")
        new_items.extend(items1)
        items2 = crawl_court(driver, "대구서부지원", "PGJ151F00")
        new_items.extend(items2)
        log.info(f"물건상세검색 소계: {len(new_items)}건")

        # ── 2. 매각예정물건 (2주 후 ~ 6주치) ────────────
        log.info("\n[2단계] 매각예정물건 수집 시작")
        items3 = crawl_court(driver, "대구지방법원", "PGJ157M00")
        new_items.extend(items3)
        items4 = crawl_court(driver, "대구서부지원", "PGJ157M00")
        new_items.extend(items4)
        log.info(f"매각예정물건 소계: {len(items3) + len(items4)}건")

        log.info(f"\n오늘 전체 수집: {len(new_items)}건")

    except Exception as e:
        log.error(f"오류: {e}")
    finally:
        driver.quit()

    # 대구 물건 필터
    daegu_items = [
        i for i in new_items
        if "대구" in i.get("address", "") or "대구" in i.get("court", "")
    ]
    log.info(f"대구 필터: {len(daegu_items)}건")

    if not daegu_items and not existing_data:
        log.warning("수집 데이터 없음")
        return

    # 누적 병합
    merged = merge_data(existing_data, daegu_items or new_items)
    final_items = list(merged.values())

    # 입찰일 기준 정렬 (가까운 순)
    final_items.sort(key=lambda x: x.get("bid_date", "9999"))

    log.info(f"✅ 최종 저장: {len(final_items)}건 (누적)")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(final_items),
            "items": final_items
        }, f, ensure_ascii=False, indent=2)

    log.info(f"💾 저장 완료 ({len(final_items)}건)")


if __name__ == "__main__":
    run()
