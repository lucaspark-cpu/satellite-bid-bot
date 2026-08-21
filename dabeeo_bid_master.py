import os
import re
import sqlite3
import requests
import urllib.parse
from datetime import datetime, timedelta

# =============================================================
# 1. 다비오(Dabeeo) 규칙 기반 스코어링 엔진
# =============================================================

KEYWORD_WEIGHTS = {
    # [Core] 데이터 출처 및 위성/항공 도메인 (+10점)
    "CORE": {
        "keywords": [
            "위성", "초소형위성", "항공사진", "정사영상", "드론", "SAR", "EO",
            "Remote Sensing", "원격탐사", "국토위성", "산림위성", "K-LEO"
        ],
        "score": 10
    },
    # [Tech] 핵심 AI 및 공간분석 기술 (+7점)
    "TECH": {
        "keywords": [
            "변화탐지", "객체식별", "지리공간", "공간정보", "디지털트윈", "디지털 트윈",
            "학습데이터", "학습 데이터", "초고해상도", "Super Resolution", "3D", 
            "Instance Segmentation", "Object Detection", "Change Detection",
            "Geospatial", "판독", "자동화", "저작도구"
        ],
        "score": 7
    },
    # [Domain] 다비오 특화 적용 도메인 및 고객사 (+5점)
    "DOMAIN": {
        "keywords": [
            "MDA", "해경", "해양경찰", "국방", "군사지도", "군수지도", "전장", "유무인",
            "국유지", "K-water", "산림", "국립공원", "농식품", "관개", "재배지", 
            "북한", "ODA", "선박", "탄소", "지적정보", "UNOPS", "NATO"
        ],
        "score": 5
    }
}

# 키워드 시너지 조합 (+15점)
COMBO_PATTERNS = [
    (r"위성", r"AI"),
    (r"위성", r"변화탐지"),
    (r"항공", r"변화탐지"),
    (r"국방", r"AI"),
    (r"해경", r"위성"),
    (r"공간정보", r"플랫폼"),
    (r"지적", r"ODA"),
    (r"학습데이터", r"구축")
]

# 감점 및 불필요 키워드 필터링 (-30점)
NEGATIVE_KEYWORDS = [
    "큐레이팅봇", "QR.here", "행사운영", "문화관람", "급식", "청소", "경비", "서버", "하드웨어"
]

def calculate_score(title: str) -> tuple[int, list]:
    """공고명 기반 규칙 기반 가중치 및 매칭 사유 산출"""
    score = 0
    reasons = []

    for neg in NEGATIVE_KEYWORDS:
        if neg in title:
            score -= 30
            reasons.append(f"제외({neg})")

    for category, data in KEYWORD_WEIGHTS.items():
        weight = data["score"]
        for kw in data["keywords"]:
            if re.search(re.escape(kw), title, re.IGNORECASE):
                score += weight
                reasons.append(f"{kw}(+{weight})")

    for p1, p2 in COMBO_PATTERNS:
        if re.search(p1, title, re.IGNORECASE) and re.search(p2, title, re.IGNORECASE):
            score += 15
            reasons.append(f"조합[{p1}+{p2}](+15)")

    return score, reasons


# =============================================================
# 2. SQLite DB 인터페이스
# =============================================================

DB_NAME = "g2b_bids.db"

def init_db():
    """DB 및 테이블 초기화"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bids (
            bid_no TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            score INTEGER,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_bids_to_db(bids: list):
    """신규 공고 DB 저장"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for bid in bids:
        cursor.execute("""
            INSERT OR IGNORE INTO bids (bid_no, title, url, score, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            bid.get('bid_no'),
            bid.get('bid_name'),
            bid.get('bid_url', ''),
            bid.get('score', 0),
            now
        ))
    conn.commit()
    conn.close()


# =============================================================
# 3. 공고 수집 메인 함수
# =============================================================

def fetch_g2b_servc_bids() -> list:
    """나라장터(G2B) 용역 공고 수집 및 필터링"""
    init_db()
    
    api_key = (
        os.getenv("G2B_API_KEY") or 
        os.getenv("SERVICE_KEY") or 
        os.getenv("G2B_SERVICE_KEY")
    )
    
    if not api_key:
        print("[WARN] G2B API 키가 설정되지 않았습니다.")
        return []

    api_key = urllib.parse.unquote(api_key)

    # 최근 3일간 조회
    now = datetime.now()
    inqrBeginDt = (now - timedelta(days=3)).strftime("%Y%m%d0000")
    inqrEndDt = now.strftime("%Y%m%d2359")

    url = "http://apis.data.go.kr/1230000/BidPublicInfoService02/getBidPstServcListInfoThng02"
    params = {
        'serviceKey': api_key,
        'numOfRows': '100',
        'pageNo': '1',
        'inqrDiv': '1',
        'inqrBeginDt': inqrBeginDt,
        'inqrEndDt': inqrEndDt,
        'type': 'json'
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        items = data.get('response', {}).get('body', {}).get('items', [])
    except Exception as e:
        print(f"[API ERROR] 나라장터 API 호출 실패: {e}")
        return []

    target_bids = []
    
    print(f"\n--- 수집 공고 {len(items)}건 검토 시작 ---")
    for item in items:
        bid_no = item.get('bidNtceNo', '')
        title = item.get('bidNtceNm', '')
        order_agency = item.get('ntceInsttNm') or item.get('dminsttNm') or '미지정 기관'
        bid_date = item.get('bidClseDt', '진행중')
        bid_url = item.get('bidNtceDtlUrl') or f"https://www.g2b.go.kr:8081/ep/invitation/ui/bidGonggoDtl.do?bidNo={bid_no}"
        region = item.get('prtcLmtRgnNm', '전국')

        score, reasons = calculate_score(title)
        print(f"[검토] 점수: {score:2d} | 공고명: {title} | 이유: {reasons}")

        # 점수 기준 설정 (5점 이상 시 이메일 리포트 포함)
        if score >= 5:
            target_bids.append({
                'bid_no': bid_no,
                'bid_name': title,
                'order_agency': order_agency,
                'bid_date': bid_date,
                'bid_url': bid_url,
                'region': region,
                'score': score,
                'source': 'G2B'
            })

    print(f"--- 필터링 통과 공고: {len(target_bids)}건 ---\n")
    return target_bids

def fetch_d2b_bids() -> list:
    """D2B 국방전자조달 수집용 (확장성 대비)"""
    return []
