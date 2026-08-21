import re

# 1. 키워드 딕셔너리 정의 (다비오 카탈로그 및 공고 이력 기반)
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

# 2. 필수 조합 (Combo) 시너지가 발생하는 조합 키워드 (+15점)
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

# 3. 감점 및 패널티 키워드 (-30점)
NEGATIVE_KEYWORDS = [
    "큐레이팅봇", "QR.here", "감리용역", "행사운영", "문화관람", "급식", "청소"
]

def calculate_dabeeo_bid_score(title: str, detail_text: str = "") -> dict:
    """
    공고 제목 및 상세 내용을 바탕으로 다비오 맞춤형 점수 산출 함수
    """
    full_text = f"{title} {detail_text}"
    score = 0
    matched_reasons = []

    # A. 감점 키워드 체크
    for neg in NEGATIVE_KEYWORDS:
        if neg in full_text:
            score -= 30
            matched_reasons.append(f"Negative({neg}): -30")

    # B. 영역별 키워드 스코어링
    for category, data in KEYWORD_WEIGHTS.items():
        weight = data["score"]
        for kw in data["keywords"]:
            # 단어 포함 여부 확인 (대소문자 무시)
            if re.search(re.escape(kw), full_text, re.IGNORECASE):
                score += weight
                matched_reasons.append(f"{category}({kw}): +{weight}")

    # C. Combo 시너지 점수
    for p1, p2 in COMBO_PATTERNS:
        if re.search(p1, full_text, re.IGNORECASE) and re.search(p2, full_text, re.IGNORECASE):
            score += 15
            matched_reasons.append(f"Combo({p1}+{p2}): +15")

    return {
        "score": score,
        "is_relevant": score >= 15,  # 임계값(Threshold) 설정 (예: 15점 이상 시 추천)
        "reasons": matched_reasons
    }

# --- 테스트 예시 ---
if __name__ == "__main__":
    sample_bids = [
        "도미니카(공) ICT기반 국립공원 기후변화 모니터링 역량 고도화 사업 PC1(시스템구축) 용역",
        "해양경찰청 MDA 5차 사업",
        "(25G043-H) AI 객체식별 기반 지리공간분석 기술 실증",
        "2026년 지능형 멀티 문화정보 큐레이팅봇 구축"
    ]

    for bid in sample_bids:
        result = calculate_dabeeo_bid_score(bid)
        print(f"공고명: {bid}")
        print(f"점수: {result['score']} | 추천여부: {result['is_relevant']}")
        print(f"사유: {', '.join(result['reasons'])}\n")
