import os
import re
import sqlite3
import requests
from datetime import datetime, timedelta

# =============================================================
# 1. 스코어링 규칙 및 키워드 정의 (Dabeeo 맞춤형)
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

# 시너지 조합 키워드 (+15점)
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

# 패널티 및 무관 공고 필터링 (-30점)
NEGATIVE_KEYWORDS = [
    "큐레이팅봇", "QR.here", "행사운영", "문화관람", "급식", "청소", "경비"
]


def calculate_score(title: str) -> tuple[int, list]:
    """공고명 기반 점수 및 매칭 사유 계산"""
    score = 0
    reasons = []

    # A. 감점 키워드
    for neg in NEGATIVE_KEYWORDS:
        if neg in title:
            score -= 30
            reasons.append(f"제외키워드({neg})")

    # B. 영역별 키워드
    for category, data in KEYWORD_WEIGHTS.items():
        weight = data["score"]
        for kw in data["keywords"]:
            if re.search(re.escape(kw), title, re.IGNORECASE):
                score += weight
                reasons.append(f"{kw}(+{weight})")

    # C. Combo 시너지
    for p1, p2 in COMBO_PATTERNS:
        if re.search(p1, title, re.IGNORECASE) and re.search(p2, title, re.IGNORECASE):
            score += 15
            reasons.append(f"조합[{p1}+{p2}](+15)")

    return score, reasons


# =============================================================
# 2. SQLite DB 관리 함수 (g2b_bot_email.py 호환)
# =============================================================

DB_PATH = "bids.db"

def init_db():
    """DB 테이블 생성 및 초기화"""
    conn = sqlite3.connect(DB_PATH)
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

def is_bid_exists(bid_no: str) -> bool:
    """이미 처리된 공고인지 확인"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM bids WHERE bid_no = ?", (bid_no,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_bids_to_db(bids: list):
    """신규 공고 DB 저장"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for bid in bids:
        cursor.execute("""
            INSERT OR IGNORE INTO bids (bid_no, title, url, score, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (bid.get('bidNtceNo'), bid.get('bidNtceNm'), bid.get('bidNtceDtlUrl'), bid.get('score', 0), now))
    conn.commit()
    conn.close()


# =============================================================
# 3. 나라장터 API 수집 및 필터링 메인 함수
# =============================================================

def fetch_g2b_servc_bids() -> list:
    """g2b_bot_email.py에서 호출하는 공고 수집 메인 함수"""
    init_db()
    
    api_key = os.getenv("G2B_API_KEY")
    if not api_key:
        print("[경고] G2B_API_KEY 환경변수가 설정되지 않았습니다.")
        return []

    # 조회 기간: 최근 3일
    now = datetime.now()
    inqrBeginDt = (now - timedelta(days=3)).strftime("%Y%m%d0000")
    inqrEndDt = now.strftime("%Y%m%d2359")

    url = "http://apis.data.go.kr/1230000/BidPublicInfoService02/getBidP顺ServcListInfoThng02"
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
        print(f"[API 오류] 나라장터 API 호출 실패: {e}")
        return []

    target_bids = []
    
    print(f"\n--- 총 {len(items)}건의 공고 수집됨 (스코어링 시작) ---")
    for item in items:
        bid_no = item.get('bidNtceNo')
        title = item.get('bidNtceNm', '')
        
        # 1) 점수 산출
        score, reasons = calculate_score(title)
        item['score'] = score
        item['reasons'] = reasons

        # 디버깅용 실시간 출력
        print(f"[검토] 점수: {score:2d} | 이유: {reasons} | 공고명: {title}")

        # 2) DB 중복 체크 및 기준점수 이상 필터링 (5점 이상)
        if score >= 5:
            if not is_bid_exists(bid_no):
                target_bids.append(item)
            else:
                print(f" -> [중복 제외] 이미 저장된 공고입니다: {bid_no}")

    print(f"--- 최종 추천 공고: {len(target_bids)}건 ---\n")
    return target_bids
