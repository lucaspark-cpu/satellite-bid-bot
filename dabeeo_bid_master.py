import os
import requests
import sqlite3
import datetime
import urllib.parse

# 1. API 인증키 및 Endpoint 설정
RAW_SERVICE_KEY = "%2BemmedaZrwpwK2FqtKT9BiUA9%2FqWfUYkm3pFh%2Fw95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg%3D%3D"
SERVICE_KEY = urllib.parse.unquote(RAW_SERVICE_KEY)

BASE_URL = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService"
G2B_SERVC_SEARCH_URL = f"{BASE_URL}/getBidPblancListInfoServcPPSSrch"
G2B_FILE_URL = f"{BASE_URL}/getBidPblancListInfoEorderAtchFileInfo"

DB_FILE = "g2b_bids.db"

# 2. 스코어링 & 키워드 설정 (README 명세 기준)
HIGH_TARGET_KEYWORDS = ["위성", "드론", "공간정보"]
WEIGHT_KEYWORDS = ["AI", "영상", "모니터링", "변화", "다비오", "인공지능", "딥러닝", "지도"]
NEGATIVE_KEYWORDS = [
    "제조", "공사", "서버", "하드웨어", "청소", "폐기물", "경비", "소방", 
    "급식", "피복", "인쇄", "차량", "임대", "배관", "전기공사"
]

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
            score INTEGER DEFAULT 0,
            grade TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def calculate_score_and_grade(bid_title):
    """README 명세 기반 연관도 스코어링 및 등급 산정"""
    # 네거티브 필터링: 제외 키워드 포함 시 자동 탈락 (0점, None)
    if any(neg in bid_title for neg in NEGATIVE_KEYWORDS):
        return 0, None

    score = 0
    grade = "중"

    # 가중치 키워드 점수 부여
    for kw in WEIGHT_KEYWORDS:
        if kw in bid_title:
            score += 10

    # 핵심 타겟 키워드 포함 여부 검사
    has_high_target = any(high_kw in bid_title for high_kw in HIGH_TARGET_KEYWORDS)
    for high_kw in HIGH_TARGET_KEYWORDS:
        if high_kw in bid_title:
            score += 20

    if has_high_target:
        grade = "상"

    # 키워드가 하나도 안 맞으면 제외
    if score == 0:
        return 0, None

    return score, grade

def fetch_rfp_file(bid_no):
    """20번 API: e발주 첨부파일(RFP) URL 및 파일명 조회"""
    params = {
        'serviceKey': SERVICE_KEY,
        'inqryDiv': '2',
        'bidNtceNo': bid_no,
        'numOfRows': '10',
        'pageNo': '1',
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
            return file_info.get('eorderAtchFileUrl', ''), file_info.get('eorderAtchFileNm', '제안요청서')
    except Exception as e:
        print(f"[WARN] RFP file fetch failed for {bid_no}: {e}")
    
    return "", ""

def fetch_g2b_servc_bids(days_back=1):
    """12번 API: 용역 입찰 공고 수집 및 스코어링 적용"""
    now = datetime.datetime.now()
    start_date = (now - datetime.timedelta(days=days_back)).strftime("%Y%m%d0000")
    end_date = now.strftime("%Y%m%d2359")

    params = {
        'serviceKey': SERVICE_KEY,
        'inqryDiv': '1',
        'inqryBgnDt': start_date,
        'inqryEndDt': end_date,
        'numOfRows': '100',
        'pageNo': '1',
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
            
            # 스코어 및 등급 계산
            score, grade = calculate_score_and_grade(bid_title)
            if grade is not None:
                bid_no = item.get('bidNtceNo', '')
                rfp_url, rfp_name = fetch_rfp_file(bid_no)
                
                bid_info = {
                    'bid_no': bid_no,
                    'bid_name': bid_title,
                    'order_agency': item.get('ntceInsttNm', '미지정'),
                    'bid_date': item.get('bidNtceDt', ''),
                    'bid_url': item.get('bidNtceDtlUrl', ''),
                    'rfp_file_url': rfp_url,
                    'rfp_file_name': rfp_name,
                    'score': score,
                    'grade': grade,
                    'source': 'G2B'
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
                INSERT INTO bids (bid_no, bid_name, order_agency, bid_date, bid_url, rfp_file_url, rfp_file_name, score, grade)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bid['bid_no'], 
                bid['bid_name'], 
                bid['order_agency'], 
                bid['bid_date'], 
                bid['bid_url'],
                bid.get('rfp_file_url', ''),
                bid.get('rfp_file_name', ''),
                bid.get('score', 0),
                bid.get('grade', '중')
            ))
            new_count += 1

    conn.commit()
    conn.close()
    return new_count

if __name__ == "__main__":
    init_db()
    print("나라장터 용역 입찰 공고 스코어링 수집 시작...")
    bids = fetch_g2b_servc_bids()
    new_added = save_bids_to_db(bids)
    print(f"수집 완료: 총 {len(bids)}건 유효 공고 수집 (신규 {new_added}건 저장됨).")
