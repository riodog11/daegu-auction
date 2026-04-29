"""
대구 법원경매 자동 수집기
============================
대법원 법원경매정보 사이트(courtauction.go.kr)에서
대구 지역 경매 물건을 자동으로 수집하고 data.json에 저장합니다.

실행 방법:
    python crawler.py          # 1회 실행
    python crawler.py --schedule  # 매일 새벽 3시 자동 실행

필요 패키지 설치:
    pip install requests beautifulsoup4 lxml schedule
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
import logging
from datetime import datetime

# ── 로그 설정 ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crawler.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── 설정 ──────────────────────────────────────────────
BASE_URL = "https://www.courtauction.go.kr"
DATA_FILE = "data.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": "https://www.courtauction.go.kr/",
}

# 대구 지역 법원 코드 (대구지방법원 + 산하 지원)
DAEGU_COURTS = {
    "B30G0000":  "대구지방법원",
    "B30B0000":  "대구지방법원 경주지원",
    "B30C0000":  "대구지방법원 김천지원",
    "B30D0000":  "대구지방법원 안동지원",
    "B30E0000":  "대구지방법원 상주지원",
    "B30F0000":  "대구지방법원 의성지원",
    "B30H0000":  "대구지방법원 영덕지원",
    "B30I0000":  "대구지방법원 포항지원",
}

# 물건 종류 코드
ITEM_TYPES = {
    "0001": "아파트",
    "0002": "다세대(빌라)",
    "0003": "단독주택",
    "0004": "상가",
    "0005": "토지",
    "0006": "오피스텔",
    "0007": "기타",
}


class AuctionCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.items = []

    def fetch(self, url, method="GET", data=None, retry=3):
        """페이지 요청 (재시도 포함)"""
        for attempt in range(retry):
            try:
                if method == "POST":
                    res = self.session.post(url, data=data, timeout=15)
                else:
                    res = self.session.get(url, timeout=15)

                res.encoding = "utf-8"
                if res.status_code == 200:
                    return res.text
                log.warning(f"HTTP {res.status_code} - {url}")

            except requests.exceptions.Timeout:
                log.warning(f"Timeout (시도 {attempt+1}/{retry}) - {url}")
            except requests.exceptions.RequestException as e:
                log.warning(f"요청 오류 (시도 {attempt+1}/{retry}): {e}")

            time.sleep(2 * (attempt + 1))  # 재시도 간격 점진적 증가

        log.error(f"모든 재시도 실패: {url}")
        return None

    # ── 목록 수집 ──────────────────────────────────────
    def get_list(self, court_code, court_name, page=1):
        """법원별 경매 목록 수집"""
        url = f"{BASE_URL}/pgj/index.on"
        data = {
            "w2xPath": "/pgj/ui/pgj100/PGJ151F00.xml",
            "courtCode": court_code,
            "searchType": "A",          # 전체
            "itemCode": "0001",         # 아파트 (필요시 반복)
            "pageNo": str(page),
            "pageSize": "20",
        }

        html = self.fetch(url, method="POST", data=data)
        if not html:
            return [], False

        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("table.tbl_list tbody tr")

        items = []
        for row in rows:
            cols = row.select("td")
            if len(cols) < 8:
                continue

            try:
                case_no = cols[0].get_text(strip=True)
                address = cols[2].get_text(strip=True)
                appraisal = cols[3].get_text(strip=True)
                min_price = cols[4].get_text(strip=True)
                bid_date = cols[5].get_text(strip=True)
                status = cols[6].get_text(strip=True)

                # 상세 페이지 링크
                link_tag = cols[0].find("a")
                detail_url = ""
                if link_tag and link_tag.get("href"):
                    detail_url = BASE_URL + link_tag["href"]

                items.append({
                    "case_no": case_no,
                    "court": court_name,
                    "address": address,
                    "appraisal_raw": appraisal,
                    "min_price_raw": min_price,
                    "bid_date": bid_date,
                    "status": status,
                    "detail_url": detail_url,
                })

            except Exception as e:
                log.debug(f"행 파싱 오류: {e}")
                continue

        # 다음 페이지 여부
        has_next = bool(soup.select_one("a.next_page"))
        return items, has_next

    # ── 상세 정보 수집 ─────────────────────────────────
    def get_detail(self, item):
        """상세 페이지에서 추가 정보 수집"""
        if not item.get("detail_url"):
            return item

        html = self.fetch(item["detail_url"])
        if not html:
            return item

        soup = BeautifulSoup(html, "lxml")

        # 기본 정보 테이블 파싱
        detail = {}
        for row in soup.select("table.tbl_view tr"):
            th = row.find("th")
            td = row.find("td")
            if th and td:
                key = th.get_text(strip=True)
                val = td.get_text(strip=True)
                detail[key] = val

        # 필요 정보 추출
        item["apt_name"]   = detail.get("물건명칭", "")
        item["area"]       = detail.get("면적", detail.get("전용면적", ""))
        item["floor"]      = detail.get("층", "")
        item["direction"]  = detail.get("방향", "")
        item["item_type"]  = detail.get("물건종류", "")
        item["case_status"]= detail.get("사건상태", "")

        # 가격 정리 (숫자만 추출)
        item["appraisal"]  = self._parse_price(item.get("appraisal_raw", ""))
        item["min_price"]  = self._parse_price(item.get("min_price_raw", ""))

        # 할인율 계산
        if item["appraisal"] and item["min_price"]:
            discount = round((1 - item["min_price"] / item["appraisal"]) * 100)
            item["discount"] = discount
        else:
            item["discount"] = 0

        # PDF 문서 링크 수집
        item["documents"] = self._get_documents(soup)

        time.sleep(0.5)  # 서버 부하 방지
        return item

    def _get_documents(self, soup):
        """PDF 문서 링크 추출"""
        docs = []
        for link in soup.select("a[href*='.pdf'], a[onclick*='pdf'], a[onclick*='PDF']"):
            name = link.get_text(strip=True)
            href = link.get("href", "") or link.get("onclick", "")
            if name and href:
                docs.append({"name": name, "url": href})
        return docs

    def _parse_price(self, text):
        """가격 텍스트에서 숫자(만원) 추출"""
        if not text:
            return 0
        # 억/만 단위 처리
        text = text.replace(",", "").replace(" ", "")
        total = 0
        if "억" in text:
            parts = text.split("억")
            total += int(re.sub(r"[^0-9]", "", parts[0]) or 0) * 10000
            if len(parts) > 1 and parts[1]:
                total += int(re.sub(r"[^0-9]", "", parts[1]) or 0)
        elif "만" in text:
            total = int(re.sub(r"[^0-9]", "", text.split("만")[0]) or 0)
        else:
            nums = re.sub(r"[^0-9]", "", text)
            total = int(nums) // 10000 if nums else 0
        return total

    # ── 메인 수집 ──────────────────────────────────────
    def run(self):
        log.info("=" * 50)
        log.info("대구 법원경매 수집 시작")
        log.info(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.info("=" * 50)

        all_items = []

        for court_code, court_name in DAEGU_COURTS.items():
            log.info(f"\n📍 {court_name} 수집 중...")
            page = 1

            while True:
                items, has_next = self.get_list(court_code, court_name, page)
                log.info(f"  페이지 {page}: {len(items)}건 수집")

                # 상세 정보 수집
                for i, item in enumerate(items):
                    log.debug(f"  상세 {i+1}/{len(items)}: {item['case_no']}")
                    detailed = self.get_detail(item)
                    all_items.append(detailed)
                    time.sleep(0.3)  # 서버 부하 방지

                if not has_next:
                    break
                page += 1
                time.sleep(1)

        log.info(f"\n✅ 총 {len(all_items)}건 수집 완료")
        self.save(all_items)

    def save(self, items):
        """data.json으로 저장"""
        output = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(items),
            "items": items
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        log.info(f"💾 data.json 저장 완료 ({len(items)}건)")


# ── 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    crawler = AuctionCrawler()

    if "--schedule" in sys.argv:
        import schedule
        log.info("⏰ 스케줄러 시작 — 매일 새벽 3시에 자동 수집")
        schedule.every().day.at("03:00").do(crawler.run)
        crawler.run()  # 시작 시 1회 즉시 실행
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        crawler.run()
