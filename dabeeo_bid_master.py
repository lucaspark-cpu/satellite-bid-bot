import re
# (기존 DB 연동 및 G2B API 호출 관련 import 구문은 유지)

# -------------------------------------------------------------
# 1. 개선된 스코어링 키워드 및 패턴 정의
# -------------------------------------------------------------
KEYWORD_WEIGHTS = {
    "CORE": {
        "keywords": [
            "위성", "초소형위성", "항공사진", "정사영상", "드론", "SAR", "EO",
            "Remote Sensing", "원격탐사", "국토위성", "산림위성", "K-LEO"
        ],
        "score": 10
    },
    "TECH": {
        "keywords": [
            "변화탐지", "객체식별", "지리공간", "공간정보", "디지털트윈", "디지털 트윈",
            "학습데이터", "학습 데이터", "초고해상도", "Super Resolution", "3D", 
            "Instance Segmentation", "Object Detection", "Change Detection",
            "Geospatial", "판독", "자동화", "저작도구"
        ],
        "score": 7
    },
    "DOMAIN": {
        "keywords": [
            "MDA", "해경", "해양경찰", "국방", "군사지도", "군수지도", "전장", "유무인",
            "국유지", "K-water", "산림", "국립공원", "농식품", "관개", "재배지", 
            "북한", "ODA", "선박", "탄소", "지적정보", "UNOPS", "NATO"
        ],
        "score": 5
    }
}

COMBO_PATTERNS = [
    (r"위성", r"AI"), (r"위성", r"변화탐지"), (r"항공", r"변화탐지"),
    (r"국방", r"AI"), (r"해경", r"위성"), (r"공간정보", r"플랫폼"),
    (r"지적", r"ODA"), (r"학습데이터", r"구 구축")
]

NEGATIVE_KEYWORDS = ["큐레이팅봇", "QR.here", "감리용역", "행사운영", "문화관람", "급식", "청소"]

def calculate_score(title: str) -> int:
    """개선된 스코어링 함수"""
    score = 0
    for neg in NEGATIVE_KEYWORDS:
        if neg in title:
            score -= 30

    for category, data in KEYWORD_WEIGHTS.items():
        weight = data["score"]
        for kw in data["keywords"]:
            if re.search(re.escape(kw), title, re.IGNORECASE):
                score += weight

    for p1, p2 in COMBO_PATTERNS:
        if re.search(p1, title, re.IGNORECASE) and re.search(p2, title, re.IGNORECASE):
            score += 15

    return score


# -------------------------------------------------------------
# 2. g2b_bot_email.py 에서 불러오는 필수 함수 선언 (이름 유지)
# -------------------------------------------------------------

def init_db():
    # 기존 DB 초기화 코드 작성
    pass

def save_bids_to_db(bids):
    # 기존 DB 저장 코드 작성
    pass

def fetch_g2b_servc_bids():
    """
    g2b_bot_email.py가 호출하는 공고 수집 및 필터링 메인 함수
    """
    # 1) 기존 API / 크롤링 호출 로직으로 raw 공고 데이터 수집
    raw_bids = [] # (기존 G2B 수집 코드 배치)

    filtered_bids = []
    for bid in raw_bids:
        title = bid.get('bidNtceNm', '') # 공고명 추출 (필드명 확인 필요)
        
        # 2) 개선된 스코어 계산
        score = calculate_score(title)
        bid['score'] = score
        
        # 3) 임계값(예: 10점 이상) 이상 공고만 필터링하여 담기
        if score >= 10:
            filtered_bids.append(bid)

    return filtered_bids
