"""
대구 법원경매 자동 수집기 v11
=====================================
- 10페이지 묶음 이후 다음 묶음 버튼 처리
- 페이징 구조 상세 분석
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import NoAlertPresentException
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


def set_daegu_filter(driver):
    driver.execute_script("""
        var selects = document.querySelectorAll('select');
        for(var sel of selects) {
            var opts = Array.from(sel.options);
            for(var opt of opts) {
                if(opt.text.includes('대구') || opt.value.includes('대구')) {
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    break;
                }
            }
        }
    """)
    time.sleep(1)


def collect_page(driver):
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
                    "case_no": case_no, "court": court, "address": address,
                    "apt_name": " ".join(address.split()[-2:]) if address else "",
                    "area": "", "floor": "", "direction": "", "item_type": "아파트",
                    "appraisal": appraisal, "min_price": min_price, "discount": discount,
                    "bid_date": bid_date, "status": "진행",
                    "lat": 35.8714, "lng": 128.6014,
                    "documents": [], "detail_url": detail_url, "blog_url": ""
                })
            except:
                continue
    return items


def analyze_paging(driver, page):
    """현재 페이지 페이징 구조 분석"""
    result = driver.execute_script("""
        var paging = [];
        
        // 모든 a 태그 중 페이지 관련
        var links = document.querySelectorAll('a');
        for(var link of links) {
            var txt = (link.textContent || '').trim();
            var onclick = link.getAttribute('onclick') || '';
            var href = link.getAttribute('href') || '';
            // 숫자이거나 다음/이전 관련
            if(/^\\d+$/.test(txt) || txt.includes('다음') || txt.includes('이전') || 
               txt.includes('>') || txt.includes('<') || onclick.includes('page') ||
               onclick.includes('Page') || onclick.includes('go')) {
                paging.push({txt: txt, onclick: onclick.slice(0,80), href: href.slice(0,50)});
            }
        }
        
        // img 태그 (다음 버튼이 이미지일 수 있음)
        var imgs = document.querySelectorAll('img');
        for(var img of imgs) {
            var alt = img.getAttribute('alt') || '';
            var src = img.getAttribute('src') || '';
            if(alt.includes('다음') || alt.includes('next') || src.includes('next') || src.includes('btn_next')) {
                var parent = img.parentElement;
                var parentOnclick = (parent && parent.getAttribute('onclick')) || '';
                paging.push({txt: 'IMG:'+alt, onclick: parentOnclick.slice(0,80), src: src.slice(0,50)});
            }
        }
        
        return paging;
    """)
    log.info(f"페이지 {page} 페이징 구조:")
    for p in (result or []):
        log.info(f"  {p}")
    return result or []


def go_next_page(driver, current_page):
    """다음 페이지로 이동"""

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

    # 방법 2: 다음 묶음 버튼 (이미지 포함)
    next_selectors = [
        "a[title='다음페이지']", "a[title='다음']",
        "a.next", ".next a", "#next",
        "img[alt='다음']", "img[alt='next']",
        "img[src*='next']", "img[src*='btn_next']",
        "a[onclick*='next']", "a[onclick*='Next']",
    ]
    for selector in next_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, selector)
            # 부모 클릭 (img의 경우)
            target = el if el.tag_name == 'a' else el.find_element(By.XPATH, "..")
            driver.execute_script("arguments[0].click();", target)
            time.sleep(3)
            dismiss_alert(driver)
            return True
        except:
            continue

    # 방법 3: onclick에서 페이지 함수 추출 후 호출
    result = driver.execute_script(f"""
        var links = document.querySelectorAll('a');
        for(var link of links) {{
            var txt = (link.textContent || link.getAttribute('title') || '').trim();
            var onclick = link.getAttribute('onclick') || '';
            // 다음 페이지 관련 링크 찾기
            if(txt.includes('다음') || txt === '>' || txt === '>>' ||
               onclick.includes('nextPage') || onclick.includes('next_page')) {{
                link.click();
                return '클릭: ' + txt + ' / ' + onclick.slice(0,50);
            }}
        }}
        
        // 숫자 페이지 중 현재+1 페이지 onclick 찾기
        for(var link of links) {{
            var onclick = link.getAttribute('onclick') || '';
            if(onclick.includes('{current_page + 1}')) {{
                link.click();
                return '숫자클릭: ' + onclick.slice(0,50);
            }}
        }}
        
        return null;
    """)

    if result:
        log.info(f"JS 클릭: {result}")
        time.sleep(3)
        dismiss_alert(driver)
        return True

    return False


def run():
    log.info("=" * 50)
    log.info("대구 법원경매 수집 시작 v11")
    log.info(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    driver = get_driver()
    all_items = []

    try:
        driver.get(f"{BASE_URL}/pgj/index.on")
        time.sleep(5)
        dismiss_alert(driver)

        # 부동산 버튼
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[value='부동산']")
            driver.execute_script("arguments[0].click();", btn)
            log.info("부동산 클릭")
            time.sleep(5)
            dismiss_alert(driver)
        except Exception as e:
            log.warning(f"부동산 버튼 실패: {e}")
            dismiss_alert(driver)

        # 대구 필터
        set_daegu_filter(driver)

        # 검색
        try:
            btn = driver.find_element(By.CSS_SELECTOR, "input[value='검색하기']")
            driver.execute_script("arguments[0].click();", btn)
            log.info("검색하기 클릭!")
            time.sleep(5)
            dismiss_alert(driver)
        except Exception as e:
            log.warning(f"검색 실패: {e}")

        log.info(f"URL: {driver.current_url}")

        # 페이지 수집
        page = 1
        prev_case_nos = set()

        while page <= 200:
            items = collect_page(driver)
            log.info(f"페이지 {page}: {len(items)}건")

            if not items:
                # 페이징 분석 후 종료
                analyze_paging(driver, page)
                break

            # 중복 체크 (같은 페이지 반복 방지)
            current_case_nos = {item["case_no"] for item in items}
            if current_case_nos == prev_case_nos:
                log.info("중복 페이지 감지 — 수집 완료")
                break
            prev_case_nos = current_case_nos

            all_items.extend(items)

            # 10페이지마다 페이징 구조 분석
            if page % 10 == 0:
                log.info(f"=== {page}페이지 페이징 구조 분석 ===")
                analyze_paging(driver, page)

            # 다음 페이지
            if not go_next_page(driver, page):
                log.info(f"다음 페이지 없음 ({page}페이지 종료)")
                # 마지막 페이지에서 페이징 분석
                analyze_paging(driver, page)
                break

            page += 1

        # 대구 필터
        daegu = [i for i in all_items if "대구" in i.get("address","") or "대구" in i.get("court","")]
        log.info(f"전체: {len(all_items)}건 / 대구: {len(daegu)}건")
        final = daegu if daegu else all_items

    except Exception as e:
        log.error(f"오류: {e}")
        final = all_items
    finally:
        driver.quit()

    log.info(f"✅ 총 {len(final)}건")

    if not final:
        log.warning("데이터 없음 — 기존 유지")
        return

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(final),
            "items": final
        }, f, ensure_ascii=False, indent=2)
    log.info(f"💾 저장 완료 ({len(final)}건)")


if __name__ == "__main__":
    run()
