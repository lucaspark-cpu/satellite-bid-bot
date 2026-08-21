import os
import re
import requests
import urllib.parse
from datetime import datetime, timedelta

# =============================================================
# 1. 다비오(Dabeeo) 맞춤형 키워드 & 가중치 규칙
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
    "큐레이팅봇", "QR.here", "행사운영", "문화관람", "급식", "청소", "경비", "서버", "하드웨어"
]

def calculate_score(title: str) -> tuple[int, list]:
    """공고명 기반 점수 및 매칭 사유 계산"""
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
# 2. 호환성 유지용 더미 함수 (DB 호환성 유지)
# =============================================================

def init_db():
    pass

def save_bids_to_db(bids: list):
    pass


# =============================================================
# 3. 공고 수집 메인 함수
# =============================================================

def fetch_g2b_servc_bids() -> list:
    """최근 60일 공고 개시일 기준 수집 및 마감일 유효 공고 최신순 정렬"""
    api_key = (
        os.getenv("G2B_API_KEY") or 
        os.getenv("SERVICE_KEY") or 
        os.getenv("G2B_SERVICE_KEY")
    )
    
    if not api_key:
        print("[WARN] G2B API 키가 환경변수에 존재하지 않습니다.")
        return []

    # API 키 정제 (줄바꿈 제거)
    api_key_clean = urllib.parse.unquote(api_key).strip().replace('\r', '').replace('\n', '')

    now = datetime.now()
    inqrBeginDt = (now - timedelta(days=60)).strftime("%Y%m%d0000")
    inqrEndDt = now.strftime("%Y%m%d2359")

    url = "https://apis.data.go.kr/1230000/BidPublicInfoService02/getBidPstServcListInfoThng02"

    params = {
        'serviceKey': api_key_clean,
        'numOfRows': '200',
        'pageNo': '1',
        'inqrDiv': '1',         # 1: 공고 개시일 기준
        'inqrBeginDt': inqrBeginDt,
        'inqrEndDt': inqrEndDt,
        'type': 'json'
    }

    items = []
    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 200:
            print(f"[API HTTP ERROR] 응답 코드: {response.status_code}")
            return []

        try:
            data = response.json()
            items = data.get('response', {}).get('body', {}).get('items', [])
            if isinstance(items, dict):
                items = [items]
        except Exception as json_err:
            print(f"[API JSON ERROR] JSON 파싱 실패: {json_err}")
            return []

    except Exception as e:
        print(f"[API Connection Error] 네트워크 호출 실패: {e}")
        return []

    target_bids = []
    current_time_str = now.strftime("%Y-%m-%d %H:%M")
    
    print(f"\n--- 최근 2개월간 나라장터 원천 공고 {len(items)}건 검토 시작 ---")
    for item in items:
        bid_no = item.get('bidNtceNo', '')
        title = item.get('bidNtceNm', '')
        order_agency = item.get('ntceInsttNm') or item.get('dminsttNm') or '미지정 기관'
        bid_date = item.get('bidClseDt', '')
        reg_dt = item.get('bidNtceDt', '')
        bid_url = item.get('bidNtceDtlUrl') or f"https://www.g2b.go.kr:8081/ep/invitation/ui/bidGonggoDtl.do?bidNo={bid_no}"
        region = item.get('prtcLmtRgnNm', '전국')

        # 마감일 지난 공고 자동 제외
        if bid_date and bid_date < current_time_str:
            continue

        score, reasons = calculate_score(title)

        if score >= 1:
            print(f"[통과] 점수: {score:2d} | 이유: {reasons} | 공고명: {title}")
            target_bids.append({
                'bid_no': bid_no,
                'bid_name': title,
                'order_agency': order_agency,
                'bid_date': bid_date if bid_date else '진행중',
                'reg_dt': reg_dt,
                'bid_url': bid_url,
                'region': region,
                'score': score,
                'source': 'G2B'
            })

    # 정렬: 1순위 점수(내림차순), 2순위 게시일시(최신순 내림차순)
    target_bids.sort(key=lambda x: (x['score'], x['reg_dt']), reverse=True)

    print(f"--- 최종 유효 공고: {len(target_bids)}건 ---\n")
    return target_bids

def fetch_d2b_bids() -> list:
    return []
