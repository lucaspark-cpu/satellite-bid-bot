import os
import time
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

# 2. 스코어링 및 키워드 설정 (다비오 도메인 맞춤 확장)
HIGH_TARGET_KEYWORDS = ["위성", "드론", "공간정보", "도미니카", "국립공원", "기하보정", "정사보정"]
WEIGHT_KEYWORDS = [
    "AI", "영상", "모니터링", "변화", "다비오", "인공지능", "딥러닝", "지도", "수치지형도", "콘텐츠",
    "ICT", "기후변화", "국제협력", "ODA", "생태", "산림", "환경", "알고리즘", "SW", "모듈"
]

# 네거티브 키워드 (단순 시설/물품/노무 공고 제거, 모듈/SW 등은 제거 대상에서 제외)
NEGATIVE_KEYWORDS = [
    "제조", "공사", "서버", "하드웨어", "청소", "폐기물", "경비", "소방", 
    "급식", "피복", "인쇄", "차량", "임대", "배관", "전기공사"
]

def init_db():
    """SQLite DB 테이블 초기화"""
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
            source TEXT DEFAULT 'G2B',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def calculate_score_and_grade(bid_title):
    """연관도 스코어링 및 등급 산정"""
    # 네거티브 필터링: 단순 하드웨어/시설/노무 공고 탈락
    if any(neg in bid_title for neg in NEGATIVE_KEYWORDS):
        return 0, None

    score = 0
    grade = "중"

    # 가중치 키워드
    for kw in WEIGHT_KEYWORDS:
        if kw in bid_title:
            score += 10

    # 핵심 타겟 키워드 (상 등급 부여)
    has_high_target = any(high_kw in bid_title for high_kw in HIGH_TARGET_KEYWORDS)
    for high_kw in HIGH_TARGET_KEYWORDS:
        if high_kw in bid_title:
            score += 20

    if has_high_target:
        grade = "상"

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
    except Exception:
        pass
    
    return "", ""

def fetch_g2b_servc_bids(days_back=7):
    """12번 API: 나라장터 용역 입찰 공고 수집 (타임아웃 및 3회 재시도 적용)"""
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

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[INFO] G2B API 호출 시도 ({attempt}/{max_retries})...")
            response = requests.get(G2B_SERVC_SEARCH_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            items = data.get('response', {}).get('body', {}).get('items', [])
            if isinstance(items, dict):
                items = items.get('item', [])

            filtered_bids = []
            for item in items:
                bid_title = item.get('bidNtceNm', '')
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
            print(f"[WARN] 시도 {attempt} 실패: {e}")
            if attempt < max_retries:
                time.sleep(5)
            else:
                print("[ERROR] G2B API 최대 재시도 횟수 초과.")
                return []

def fetch_d2b_bids():
    """국방전자조달(D2B) 공고 수집 (기존 로직 유지)"""
    # 기존 프로젝트의 D2B 수집 코드가 있을 경우 여기에 유지됩니다.
    return []

def save_bids_to_db(bids):
    """신규 공고 DB 저장"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    new_count = 0

    for bid in bids:
        cursor.execute("SELECT bid_no FROM bids WHERE bid_no = ?", (bid['bid_no'],))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO bids (bid_no, bid_name, order_agency, bid_date, bid_url, rfp_file_url, rfp_file_name, score, grade, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bid['bid_no'], 
                bid['bid_name'], 
                bid['order_agency'], 
                bid['bid_date'], 
                bid['bid_url'],
                bid.get('rfp_file_url', ''),
                bid.get('rfp_file_name', ''),
                bid.get('score', 0),
                bid.get('grade', '중'),
                bid.get('source', 'G2B')
            ))
            new_count += 1

    conn.commit()
    conn.close()
    return new_count

if __name__ == "__main__":
    init_db()
    print("나라장터 용역 입찰 공고 수집 및 스코어링 시작...")
    bids = fetch_g2b_servc_bids(days_back=7)
    new_added = save_bids_to_db(bids)
    print(f"수집 완료: 총 {len(bids)}건 유효 공고 수집 (신규 {new_added}건 DB 저장됨).")
