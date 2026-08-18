import os
import requests
import sqlite3
import datetime
import urllib.parse

# 1. API 인증키 설정 (원문 디코딩 상태로 안전하게 변환)
RAW_SERVICE_KEY = "%2BemmedaZrwpwK2FqtKT9BiUA9%2FqWfUYkm3pFh%2Fw95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg%3D%3D"
SERVICE_KEY = urllib.parse.unquote(RAW_SERVICE_KEY)

# API Endpoints (12번: 용역 검색, 20번: e발주 첨부파일)
G2B_SERVC_SEARCH_URL = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoServcPPSSrch"
G2B_FILE_URL = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPblancListInfoEorderAtchFileInfo"

DB_FILE = "g2b_bids.db"
SEARCH_KEYWORDS = ["위성", "공간정보", "AI", "영상", "다비오"]

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bids (
            bid_no TEXT PRIMARY KEY,
            bid_name TEXT,
            order_agency TEXT,
            bid_date TEXT,
            bid_url TEXT,
            rfp_file_url TEXT,
            rfp_file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def fetch_rfp_file(bid_no):
    params = {
        'serviceKey': SERVICE_KEY,
        'numOfRows': '10',
        'pageNo': '1',
        'bidNtceNo': bid_no,
        'type': 'json'
    }
    try:
        res = requests.get(G2B_FILE_URL, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        items = data.get('response', {}).get('body', {}).get('items', [])
        if isinstance(items, dict):
            items = items.get('item', [])
        
        if items:
            file_info = items[0] if isinstance(items, list) else items
            return file_info.get('eOrderAtchFileUrl', ''), file_info.get('eOrderAtchFileNm', '제안요청서')
    except Exception as e:
        print(f"[WARN] RFP file fetch failed for {bid_no}: {e}")
    
    return "", ""

def fetch_g2b_servc_bids(days_back=1):
    now = datetime.datetime.now()
    start_date = (now - datetime.timedelta(days=days_back)).strftime("%Y%m%d0000")
    end_date = now.strftime("%Y%m%d2359")

    params = {
        'serviceKey': SERVICE_KEY,
        'numOfRows': '100',
        'pageNo': '1',
        'inptStrtDt': start_date,
        'inptEndDt': end_date,
        'type': 'json'
    }

    try:
        response = requests.get(G2B_SERVC_SEARCH_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        items = data.get('response', {}).get('body', {}).get('items', [])
        if isinstance(items, dict):
            items = items.get('item', [])

        filtered_bids = []
        for item in items:
            bid_title = item.get('bidNtceNm', '')
            if any(keyword in bid_title for keyword in SEARCH_KEYWORDS):
                bid_no = item.get('bidNtceNo', '')
                rfp_url, rfp_name = fetch_rfp_file(bid_no)
                
                bid_info = {
                    'bid_no': bid_no,
                    'bid_name': bid_title,
                    'order_agency': item.get('ntceInsttNm', '미지정'),
                    'bid_date': item.get('bidNtceDt', ''),
                    'bid_url': item.get('bidNtceDtlUrl', ''),
                    'rfp_file_url': rfp_url,
                    'rfp_file_name': rfp_name
                }
                filtered_bids.append(bid_info)

        return filtered_bids

    except Exception as e:
        print(f"[ERROR] G2B API Request failed: {e}")
        return []

def save_bids_to_db(bids):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    new_count = 0

    for bid in bids:
        cursor.execute("SELECT bid_no FROM bids WHERE bid_no = ?", (bid['bid_no'],))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO bids (bid_no, bid_name, order_agency, bid_date, bid_url, rfp_file_url, rfp_file_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                bid['bid_no'], 
                bid['bid_name'], 
                bid['order_agency'], 
                bid['bid_date'], 
                bid['bid_url'],
                bid.get('rfp_file_url', ''),
                bid.get('rfp_file_name', '')
            ))
            new_count += 1

    conn.commit()
    conn.close()
    return new_count

if __name__ == "__main__":
    init_db()
    print("나라장터 용역 입찰 공고 수집 시작...")
    bids = fetch_g2b_servc_bids()
    new_added = save_bids_to_db(bids)
    print(f"수집 완료: 총 {len(bids)}건 중 신규 {new_added}건 저장됨.")
