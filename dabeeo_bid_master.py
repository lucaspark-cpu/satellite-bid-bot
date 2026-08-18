import os
import requests
import sqlite3
import datetime
import urllib.parse

# 1. API 인증키 설정 및 URL Encoded 처리
RAW_SERVICE_KEY = "https://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblcnInfoList01" # 사용자 발급 키
SERVICE_KEY = urllib.parse.quote(RAW_SERVICE_KEY, safe='') if "%" not in RAW_SERVICE_KEY else RAW_SERVICE_KEY

G2B_BASE_URL = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblcnInfoList01"
DB_FILE = "g2b_bids.db"

# 검색 키워드 설정 (위성/공간정보 관련)
SEARCH_KEYWORDS = ["위성", "공간정보", "AI", "영상", "다비오"]

def init_db():
    """입찰 공고 정보를 저장할 SQLite DB 초기화"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bids (
            bid_no TEXT PRIMARY KEY,
            bid_name TEXT,
            order_agency TEXT,
            bid_date TEXT,
            bid_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def fetch_g2b_bids(days_back=1):
    """G2B OpenAPI를 호출하여 지정된 일수만큼의 입찰 공고 수집"""
    now = datetime.datetime.now()
    start_date = (now - datetime.timedelta(days=days_back)).strftime("%Y%m%d0000")
    end_date = now.strftime("%Y%m%d2359")

    params = {
        'serviceKey': urllib.parse.unquote(SERVICE_KEY),
        'numOfRows': '100',
        'pageNo': '1',
        'inptDtOrder': 'DESC',
        'inptStrtDt': start_date,
        'inptEndDt': end_date,
        'type': 'json'
    }

    try:
        response = requests.get(G2B_BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        items = data.get('response', {}).get('body', {}).get('items', [])
        if isinstance(items, dict):
            items = items.get('item', [])

        filtered_bids = []
        for item in items:
            bid_title = item.get('bidNtceNm', '')
            if any(keyword in bid_title for keyword in SEARCH_KEYWORDS):
                bid_info = {
                    'bid_no': item.get('bidNtceNo', ''),
                    'bid_name': bid_title,
                    'order_agency': item.get('ntceInsttNm', '미지정'),
                    'bid_date': item.get('bidNtceDt', ''),
                    'bid_url': item.get('bidNtceDtlUrl', '')
                }
                filtered_bids.append(bid_info)

        return filtered_bids

    except Exception as e:
        print(f"[ERROR] API Request failed: {e}")
        return []

def save_bids_to_db(bids):
    """신규 공고 건만 DB에 저장 및 새로 추가된 건수 반환"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    new_count = 0

    for bid in bids:
        cursor.execute("SELECT bid_no FROM bids WHERE bid_no = ?", (bid['bid_no'],))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO bids (bid_no, bid_name, order_agency, bid_date, bid_url)
                VALUES (?, ?, ?, ?, ?)
            ''', (bid['bid_no'], bid['bid_name'], bid['order_agency'], bid['bid_date'], bid['bid_url']))
            new_count += 1

    conn.commit()
    conn.close()
    return new_count

if __name__ == "__main__":
    init_db()
    print("나라장터 입찰 공고 수집 시작...")
    bids = fetch_g2b_bids()
    new_added = save_bids_to_db(bids)
    print(f"수집 완료: 총 {len(bids)}건 중 신규 공고 {new_added}건 저장됨.")
