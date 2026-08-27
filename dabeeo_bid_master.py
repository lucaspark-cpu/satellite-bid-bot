# -*- coding: utf-8 -*-
"""
dabeeo_bid_master.py — Dabeeo 입찰공고 규칙기반 스코어링 엔진 (v2)

설계 원칙
---------
1) 평평한 키워드 합산이 아니라 '레이어'로 판정한다.
   L0 정규화 → L1 범위판정(스코어링 대상인가) → L2 하드제외 → L3 동형이의어 가드
   → L4 코어/미드/인접/약가중 가산 → L5 동시출현 보너스 → L6 컨텍스트(기관/금액)
   → L7 허들 + 등급 매핑
2) 매칭된 키워드는 '왜 떴는지'와 함께 반환한다 (ScoreResult.reasons).
3) 비밀값은 코드에 두지 않는다. 전부 os.environ 에서 읽는다.

외부 네트워크 호출은 fetch_g2b_bids() 에서만 발생한다.
"""

from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - 스코어링 단독 테스트 시 requests 불필요
    requests = None
    HTTPAdapter = None
    Retry = None

# =============================================================================
# 1. 시스템 통합 글로벌 설정
# =============================================================================

KST = timezone(timedelta(hours=9))

DB_PATH = os.environ.get("BID_DB_PATH", "g2b_bids.db")

# 수신자: 환경변수 RECEIVER_EMAIL(콤마 구분)에서 읽는다. 코드에 하드코딩하지 않는다.
RECEIVERS: List[str] = [
    e.strip() for e in os.environ.get("RECEIVER_EMAIL", "").split(",") if e.strip()
]

# API가 자체 필터링(bidNtceNm)해 줄 고정밀 시드 키워드.
# 100건 무필터 수집 후 클라이언트 필터링하지 말고, 이 목록으로 N회 질의한다.
KEYWORDS: List[str] = [
    "위성영상",
    "위성정보",
    "초소형위성",
    "정사영상",
    "항공사진",
    "원격탐사",
    "변화탐지",
    "객체탐지",
    "공간정보",
    "지리정보",
    "수치지형도",
    "학습데이터",
    "데이터셋",
    "디지털트윈",
    "드론",
    "판독",
    "지도제작",
    "위성",
]

# API 엔드포인트 (https 강제)
G2B_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
G2B_SERVC_OP = "getBidPblancListInfoServcPPSSrch"   # 용역
G2B_THNG_OP = "getBidPblancListInfoThngPPSSrch"     # 물품(옵션, 기본 미사용)

# 방위사업청_군수품조달정보 입찰공고_GW (국방전자조달/D2B)
D2B_BASE = "https://apis.data.go.kr/1690000/BidPblancInfoService"
D2B_DMSTC_LIST_OP = "getDmstcCmpetBidPblancList"    # 국내 경쟁입찰공고 목록

HTTP_TIMEOUT = (5, 20)      # (connect, read)
MAX_PAGES = 10
NUM_OF_ROWS = 100

# D2B는 개발계정 일일 트래픽이 100건으로 낮아, 키워드별 반복 질의(G2B 방식) 대신
# 공고일자 구간으로 1~수 회만 조회하고 calculate_score()로 클라이언트단 필터링한다.
D2B_MAX_PAGES = 5
D2B_NUM_OF_ROWS = 100

TIER_HIGH = "상"
TIER_MID = "중"
TIER_LOW = "하"
TIER_DROP = "제외"

SCORE_HIGH_CUT = 50         # README 기준 유지
SCORE_MID_CUT = 20          # 20점 미만은 리포트 제외
SCORE_CAP = 100

# =============================================================================
# 2. 다비오 고도화 스코어링 — 키워드 테이블
# =============================================================================

# --- L2 하드 제외: 걸리면 즉시 사망 (spaced 텍스트에 정규식으로 적용) -------
# 청/부로 끝나는 기관명 오탐 방지를 위한 lookbehind/lookahead 포함.
NEGATIVE_KEYWORDS: List[str] = [
    # '항공사진'의 항[공사]진, '한국도로공사' 같은 기관명 오탐을 lookaround로 차단
    r"(?<!항)(?<!도로)(?<!자원)(?<!정보)(?<!철도)(?<!전력)(?<!가스)(?<!주택)"
    r"(?<!관광)(?<!어촌)(?<!환경)(?<!조폐)(?<!방송)(?<!석유)(?<!광해)공사(?!진)",
    r"제조",
    r"(?<!림청)(?<!찰청)(?<!상청)(?<!달청)(?<!무청)(?<!산청)청사",
    r"리모델링",
    r"증축|신축|개축|철거|해체",
    r"급식|조리|식자재|위탁\s*급식",
    r"청소|미화|방역|소독|제초|방제",
    r"경비(?!절감)|무인\s*경비",
    r"인쇄|출판|소식지|기념품|홍보물",
    r"행사\s*대행|축제\s*대행|의전\s*대행",
    r"보험",
    r"차량|셔틀|버스\s*임차",
    r"도장|방수|창호|승강기|엘리베이터|조경|가구|피복|의약품",
    r"(?<!불법)(?<!위반)(?<!무허가)(?<!가설)건축(?!물대장)|토목|전기\s*공사"
    r"|소방(?!청)|냉난방|공조|급수|하수|폐기물",
    r"서버|스토리지|하드웨어|노트북|프린터|복사기|사무용품|소모품",
    r"도서\s*구입|우편|주차\s*관리",
    r"영상\s*회의|화상\s*회의|영상\s*음향|방송\s*장비|음향\s*설비",
]

# --- L2b 소프트 제외: 구제(rescue) 조건을 만족하면 감점으로 전환 -----------
SOFT_EXCLUDE_KEYWORDS: List[str] = [
    r"유지\s*관리",
    r"유지\s*보수",
    r"구매|구입|납품",
    r"임차|임대",
    r"교육(?!청|부)|연수(?!원|구)|역량\s*강화|강사|과정\s*운영",
    r"설치",
    r"위탁\s*운영",
]
SOFT_EXCLUDE_PENALTY = -25

# --- L2c 감점 키워드: 죽이지는 않지만 강한 감점 ------------------------------
# 감리는 다비오 스코프가 아니다(설계·시공 감독). 그러나 '감리'가 들어간 ODA 사업 중
# 실제 데이터 구축이 섞인 건이 있어 하드킬 대신 -35 감점으로 처리한다.
PENALTY_KEYWORDS: Dict[str, int] = {
    r"감리": -35,
    r"타당성\s*조사": -10,
}

# --- L1 범위 밖: G2B/D2B 입찰공고가 아닌 별도 경로 ---------------------------
OUT_OF_SCOPE_PATTERNS: List[str] = [
    r"공모(전)?",
    r"(참여|참가)?\s*기업\s*모집|모집\s*공고|수요\s*조사",
    r"\brfi\b|\blta\b|\brfq\b",
    r"신속\s*상용화",
    r"혁신\s*기업\s*지정|기관\s*지정",
    r"바우처\s*(공급|수요)\s*기업",
]


# --- L4 브랜드(BRAND) : 등장 시 거의 확정 신호 [출처 C = 카탈로그 원문] --------
BRAND_WEIGHT_KEYWORDS: Dict[str, int] = {
    "다비오": 40,
    "어스아이": 40,
    "지오스튜디오": 40,
    "다비오맵스": 40,
    "지오인텔리전스": 35,
}

# --- L4 코어(HIGH) : 다비오 핵심 역량 직결 ----------------------------------
HIGH_WEIGHT_KEYWORDS: Dict[str, int] = {
    # 데이터 소스
    "위성영상": 35,
    "위성정보": 30,
    "초소형위성": 35,
    "초소형체계": 25,
    "국토위성": 30,
    "상용위성": 30,
    "위성": 20,           # 동형이의어 가드 필수
    "항공사진": 30,
    "정사영상": 30,
    "원격탐사": 30,
    "드론": 30,           # 동형이의어 가드 필수
    "라이다": 25,
    "합성개구레이더": 30,
    "수치표고모델": 25,
    # 시그니처 기술
    "변화탐지": 30,
    "변화이력": 25,
    "객체탐지": 30,
    "판독": 30,
    "초해상화": 30,
    "세그멘테이션": 25,
    "학습데이터": 30,
    "데이터셋": 30,
    "컴퓨터비전": 20,
    # 공간정보 / 지도
    "공간정보": 30,
    "지리정보": 30,
    "지리공간": 30,
    "수치지형도": 30,
    "지도": 20,           # 동형이의어 가드 필수
    "군사지도": 32,
    "군수지도": 32,
    "지적": 25,           # 동형이의어 가드 필수
    "디지털트윈": 30,
    # 국방/해양 도메인
    "해양상황인식": 30,
    "감시정찰": 30,
    # --- 카탈로그 반영: 5대 코어 AI 모델 (초해상화·세그멘테이션·3D재구축·객체탐지·변화탐지)
    "3차원재구축": 30,       # C: 3D Reconstruction (LOD 1.2 / Mesh & Texturing)
    "3차원공간정보": 32,     # D: 3차원 국토공간정보 / 디지털트윈국토 공고 계열
    "lod": 20,               # C
    "텍스처링": 20,          # C
    # --- 카탈로그 반영: 과소반영 역량 (U1~U14)
    "정밀도로지도": 32,      # D: GEO-STUDIO 노드링크·차선수·제한속도 UI
    "노드링크": 30,          # C(한글 UI)
    "노면표시": 25,          # C: 횡단보도/직진/진입금지 탐지
    "선박탐지": 32,          # C: SAR Ship Detection
    "불법건축물": 32,        # C: Illegal Building Detection (3년 연속 실적)
    "산림황폐화": 30,        # C: Deforestation
    "고사목": 30,            # C: Endangered/Dead Abies
    "개체목": 28,            # C: Tree detection (개체 단위)
    "전장환경": 32,          # C: 3D Battle Field
    "유무인복합": 30,        # C: Manned-Unmanned Teaming
    "도심항공교통": 30,      # C: UAM / UAM TEAM KOREA
    "버티포트": 28,          # C: Vertiport
    "저궤도위성": 28,        # C: K-LEO TF
    "플랜테이션": 30,        # C: Oil Palm Plantation
    "탄소흡수량": 30,        # C: CO2_ABSORPTION_RATE
    "탄소배출권": 30,        # C: carbon credit
    "산림탄소": 28,          # D
    "국유재산": 30,          # C: KAMCO 국유지 변화탐지 계약
    "지적재조사": 25,        # I: 지적 행정 인접
    "급경사지": 25,          # C: steep slopes 무방문 조사
    "산사태": 22,            # D
    "침수흔적": 22,          # D
    "식생지수": 25,          # C: EVI / EVI AVG View
    "영상융합": 28,          # C: heterogeneous image fusion / pan-sharpening
    "방산혁신기업": 30,      # C: 방산혁신기업 선정서(방위사업청, 2023)
    "표적정보": 28,          # D
    "데이터라벨링": 22,      # C: Data Labeling
}

# --- L4 미드(MID) : 기술·사업 형태 -----------------------------------------
MID_WEIGHT_KEYWORDS: Dict[str, int] = {
    "인공지능": 15,
    "딥러닝": 15,
    "빅데이터": 15,
    "분석": 15,
    "탐지": 15,
    "분류": 15,
    "모니터링": 15,
    "자동화": 15,
    "플랫폼": 15,
    "시스템구축": 12,
    "데이터베이스구축": 15,
    "고도화": 15,
    "실증": 15,
    "품질관리": 15,
    "전처리": 15,
    "saas": 15,
    "저작도구": 12,
    "설계": 12,
    "지능형": 10,
    "시스템": 10,          # 가드 필요
    "관제": 10,
    "클라우드": 10,
    # --- 카탈로그 반영
    "실태조사": 12,          # C: 무방문 현황조사 포지션
    "불법조업": 15,          # C: Illegal Ship Detection
    "공역": 12,              # C: Urban Airspace / Aerial corridor
    "온실가스": 12,          # D
    "데이터가공": 12,        # D
    "다중센서융합": 15,      # C: multi-source data fusion
    "시계열": 12,            # C: changes over time
    "oda": 12,               # C: 도미니카·베트남·인도네시아
    "무단점유": 15,          # C: KAMCO 국유지 문맥
    "개발행위": 12,          # D
    "임상": 10,              # D: 임상변화(산림)
}

# --- L4 인접(ADJACENT) -------------------------------------------------------
# ⚠️ 이 그룹 전체는 '입찰 이력(history-only)' 근거다. 회사소개 카탈로그(26p,
#    지오스페이셜 AI 라인)에는 실내지도·측위·경로안내·문화·전시·리테일 서술이
#    전혀 없다. 따라서 MID 이하로만 유지하고 '상' 허들 자격은 주지 않는다.
ADJACENT_KEYWORDS: Dict[str, int] = {
    "qr": 15,               # H(history-only)
    "실내지도": 12,          # H — 카탈로그 근거 부재
    "실내측위": 12,          # H — 카탈로그 근거 부재
    "길찾기": 12,
    "관람": 12,
    "박물관": 12,
    "미술관": 12,
    "모빌리티": 12,
    "내비게이션": 12,
    "문화": 10,
    "전시": 10,
    "관광": 10,
}

# --- L4 약가중(WEAK) : 경계선 판정용. 단독으로는 등급을 만들지 못한다 --------
WEAK_KEYWORDS: Dict[str, int] = {
    "구축": 6,
    "개발": 8,
    "제작": 8,
    "활용": 8,
    "촬영": 8,
    "영상": 8,            # 가드 필요
    "연구": 6,
    "시험": 6,
    "공간": 5,            # 가드 필요
}

# --- L3 동형이의어 가드: (키워드 → 무효화 컨텍스트 정규식) ------------------
# 이 표가 현행 substring 매칭 대비 가장 큰 개선점이다.
GUARDS: Dict[str, List[str]] = {
    "위성": [
        r"위성방송", r"위성통신", r"위성dmb", r"위성tv", r"위성안테나",
        r"위성수신", r"위성전화", r"위성항법", r"위성중계", r"위성라디오",
        r"기상위성수신", r"위성망", r"셋톱박스", r"중계기", r"위성도시",
        r"위성사무소", r"위성캠퍼스",
    ],
    "지도": [
        r"지도점검", r"학습지도", r"지도사", r"지도교사", r"생활지도",
        r"지도자", r"지도위원", r"진로지도", r"지도감독", r"지도력",
        r"지도부", r"지도편달", r"영농지도", r"기술지도", r"지도관",
        r"현장지도", r"안전지도점검", r"컨설팅지도", r"지도급",
    ],
    "영상": [
        r"홍보영상", r"영상장비", r"영상회의", r"영상편집", r"영상물",
        r"영상콘텐츠", r"영상보안", r"영상감시", r"영상정보처리기기",
        r"cctv", r"영상음향", r"뮤직비디오", r"영상관람", r"교육영상",
        r"영상제작대행", r"의료영상", r"영상진단", r"유튜브", r"영상스튜디오",
    ],
    "드론": [
        r"드론조종", r"드론교육", r"드론자격", r"드론체험", r"드론축구",
        r"드론기체", r"드론실기", r"드론레이싱", r"드론방제", r"드론쇼",
        r"드론정비", r"조종자양성", r"드론자격증",
    ],
    "공간": [
        r"공간리모델링", r"공간조성", r"유휴공간", r"사무공간", r"공간개선",
        r"주차공간", r"공간재구조화", r"휴게공간",
    ],
    "지적": [
        r"지적재산", r"지적장애", r"지적소유", r"지적능력",
    ],
    "시스템": [
        r"경비시스템", r"소방시스템", r"냉난방시스템", r"방송시스템",
        r"급식시스템", r"출입통제시스템",
    ],
    "분석": [
        r"성분분석", r"수질분석", r"혈액분석", r"재무분석",
    ],
    "전시": [
        r"전시대여", r"전시부스",
    ],
    "문화": [
        r"문화상품권", r"문화체육센터공사",
    ],
    # --- 카탈로그 §10 동형이의어 함정 반영 ---------------------------------
    "판독": [          # H07
        r"판독기", r"카드판독", r"지문판독", r"계량기판독", r"검침",
        r"판독원", r"바코드판독", r"마크판독",
    ],
    "탐지": [          # H06
        r"누수탐지", r"누출탐지", r"지하시설물탐지", r"금속탐지", r"침입탐지",
        r"화재탐지", r"가스누출", r"열탐지", r"지뢰탐지기구매",
    ],
    "플랫폼": [        # H13
        r"승강장", r"물류플랫폼", r"배송플랫폼", r"플랫폼공사", r"역사플랫폼",
    ],
    "3차원재구축": [   # H12
        r"3d프린", r"3d프린팅", r"애니메이션", r"캐릭터", r"게임",
    ],
    "데이터라벨링": [  # H24
        r"라벨지", r"라벨프린터", r"라벨인쇄", r"제품라벨",
    ],
    "산림황폐화": [    # H09 (시공성 산림사업과 구분)
        r"숲가꾸기", r"임도개설", r"산림욕장",
    ],
    "식생지수": [],
    "공역": [r"공역사", r"항공사공역? 임차"],
}

# --- L5 동시출현 계열 -------------------------------------------------------
SOURCE_FAMILY = {
    "위성영상", "위성정보", "초소형위성", "초소형체계", "국토위성", "상용위성",
    "위성", "항공사진", "정사영상", "원격탐사", "드론", "라이다",
    "합성개구레이더", "수치표고모델",
}
# 브랜드 토큰은 사실상 확정 신호이므로 도메인 계열로 취급한다.
BRAND_FAMILY = set(BRAND_WEIGHT_KEYWORDS)
GEO_FAMILY = {
    "공간정보", "지리정보", "지리공간", "수치지형도", "지도", "군사지도",
    "군수지도", "지적", "정사영상", "정밀도로지도", "노드링크",
    "국유재산", "3차원공간정보", "lod",
}
# 다비오 시그니처 기술: 원천영상 없이도 '상' 강신호로 인정한다.
SIGNATURE_FAMILY = {
    "변화탐지", "변화이력", "원격탐사", "정사영상", "판독", "초해상화",
    "세그멘테이션", "군사지도", "군수지도", "수치지형도", "해양상황인식",
    "감시정찰",
    # 카탈로그 반영 시그니처
    "3차원재구축", "선박탐지", "불법건축물", "산림황폐화", "고사목", "개체목",
    "전장환경", "유무인복합", "노드링크", "정밀도로지도", "노면표시",
    "탄소흡수량", "탄소배출권", "산림탄소", "국유재산", "영상융합",
    "3차원공간정보", "텍스처링",
    "식생지수", "플랜테이션", "도심항공교통", "버티포트", "저궤도위성",
    "표적정보", "급경사지",
}
# 제품/플랫폼 계열: 허들만 통과시키고 '상' 강신호로는 인정하지 않는다.
# (원천 데이터 계열이 없으면 '상'을 주지 않는다는 README 허들의 정신을 지킴)
HURDLE_EXTRA_FAMILY = {"디지털트윈", "컴퓨터비전"}
# 도메인 판정 통합 집합
DOMAIN_FAMILY = SOURCE_FAMILY | GEO_FAMILY | SIGNATURE_FAMILY | BRAND_FAMILY
TECH_FAMILY = {
    "인공지능", "딥러닝", "빅데이터", "분석", "탐지", "분류", "모니터링",
    "자동화", "플랫폼", "시스템구축", "데이터베이스구축", "고도화", "실증",
    "품질관리", "전처리", "saas", "저작도구", "설계", "시스템", "관제",
    "객체탐지", "변화탐지", "판독", "초해상화", "세그멘테이션",
    "학습데이터", "데이터셋", "컴퓨터비전",
    "3차원재구축", "영상융합", "데이터라벨링", "데이터가공", "다중센서융합",
    "실태조사", "시계열",
}
COOCCUR_BONUS = 20

# --- L6 발주기관 화이트리스트 (+15, 중복 가산 없음) --------------------------
AGENCY_WHITELIST: List[str] = [
    "한국항공우주연구원", "항우연", "우주항공청", "국토지리정보원",
    "한국국토정보공사", "lx공사", "국토교통부", "산림청", "국립산림과학원",
    "한국임업진흥원", "해양경찰청", "해경", "해양수산부", "국립해양조사원",
    "한국해양과학기술원", "한국수자원공사", "k-water", "한국도로공사",
    "한국농어촌공사", "농촌진흥청", "농림축산식품부", "방위사업청",
    "국방과학연구소", "국방부", "합동참모본부", "육군", "해군", "공군",
    "통일부", "기상청", "환경부", "국립공원공단", "한국전자통신연구원",
    "한국국제협력단", "koica", "행정안전부", "국가정보자원관리원",
    "한국지능정보사회진흥원", "nia",
]
AGENCY_BONUS = 15

# --- L6b 참가자격 게이트 -----------------------------------------------------
# 카탈로그가 확인해 준 보유 자격: 방산혁신기업(방위사업청 2023.11), 우수기업연구소
# ATC+(산업부 2023.07), KARI 패밀리기업(2024.04), ICT 미래유니콘(과기정통부 2021).
# 아래 자격들은 카탈로그에 '없다'. 보유 여부를 코드가 판정할 수 없으므로
# 감점하지 않고 UNKNOWN_ELIGIBILITY 플래그를 세워 사람 검토로 라우팅한다.
# (제주 건이 공간정보사업자·영상처리업 미보유로 탈락한 사례가 이 게이트의 근거)
ELIGIBILITY_PATTERNS: Dict[str, str] = {
    r"gs\s*인증|good\s*software": "GS인증",
    r"직접\s*생산\s*확인": "직접생산확인증명",
    r"공간정보\s*사업자|공간정보산업\s*신고": "공간정보사업자 등록",
    r"측량업\s*등록|항공사진측량업": "측량업 등록",
    r"영상처리업": "영상처리업 등록",
    r"소프트웨어\s*사업자": "소프트웨어사업자 신고",
    r"정보통신\s*공사업": "정보통신공사업 등록",
    r"엔지니어링\s*사업자": "엔지니어링사업자 신고",
    r"iso\s*9001|iso\s*27001|iso\s*14001": "ISO 인증",
    r"csap|클라우드\s*보안\s*인증": "CSAP",
    r"cc\s*인증|공통평가기준": "CC인증",
    r"g[\s-]?pass": "G-PASS 지정",
}

# --- L0.5 실제 제안/투찰 이력 (Lucas 정리, 2026-08) -------------------------
# '검토/모니터링만' 한 건이나 'RFP까지 갔다 드롭'한 건은 제외하고,
# 다비오가 실제로 제안서·입찰서를 제출까지 진행한 건만 포함한다.
# 새 공고 제목이 이 패턴과 min_hits 이상 겹치면 통상 스코어링을 건너뛰고
# 즉시 '상'으로 고정한다 (하드제외/범위밖 판정보다도 우선 적용).
WON_BID_PROJECTS: List[Dict[str, Any]] = [
    {
        "name": "도미니카(공) ICT기반 국립공원 기후변화 모니터링 역량 고도화 사업 PC1(시스템구축) 용역",
        "required": ["도미니카", "국립공원"],  # '도미니카' 단독으로는 무관한 '도미니카 ODA 감리용역'과 충돌
    },
    {
        "name": "KSIS 데이터 기반 초소형위성 활용시스템 개발 및 시험 용역",
        "required": ["ksis"],  # 유일 식별 가능한 고유어(다른 항우연 건과 구분) — normalize()가 소문자화하므로 소문자로 매칭
    },
    {
        "name": "초소형위성체계 활용시스템 예비설계 및 활용기술 개발 용역",
        "required": ["초소형위성", "활용시스템", "예비설계"],  # 3개 모두 겹쳐야 매칭
    },
    {
        "name": "파주시 정사영상 제작 사업",
        "required": ["파주", "정사영상"],
    },
    {
        "name": "군사지도 구축 사업",
        "required": ["군사지도"],
    },
    {
        "name": "군수지도 제작 용역",
        "required": ["군수지도"],
    },
]


def _match_won_project(compact_title: str) -> Optional[Dict[str, Any]]:
    for proj in WON_BID_PROJECTS:
        required = proj["required"]
        if all(kw in compact_title for kw in required):
            return {"name": proj["name"], "hits": required}
    return None


PRICE_FLOOR = 30_000_000          # 3천만원 미달 → 감점
PRICE_FLOOR_PENALTY = -15

# =============================================================================
# 3. L0 정규화
# =============================================================================

_BRACKETS = "「」『』【】〔〕[]()（）<>《》〈〉{}"
_PUNCT = "·,.;:/\\|~!?\"'’‘“”＿_-–—+*&#%@^"

# 라틴 약어 → 한글 정칙화 (한글 인접에서도 동작하도록 커스텀 경계 사용)
_LATIN_CANON: List[Tuple[str, str]] = [
    (r"(?<![a-z0-9])a\.?i\.?(?![a-z0-9])", "인공지능"),
    (r"(?<![a-z0-9])artificial\s+intelligence(?![a-z0-9])", "인공지능"),
    (r"(?<![a-z0-9])(gis|g\.i\.s)(?![a-z0-9])", "지리정보"),
    (r"(?<![a-z0-9])sar(?![a-z0-9])", "합성개구레이더"),
    (r"(?<![a-z0-9])mda(?![a-z0-9])", "해양상황인식"),
    (r"(?<![a-z0-9])isr(?![a-z0-9])", "감시정찰"),
    (r"(?<![a-z0-9])(uav|uas)(?![a-z0-9])", "드론"),
    (r"(?<![a-z0-9])(ortho|orthophoto|orthoimage)(?![a-z0-9])", "정사영상"),
    (r"(?<![a-z0-9])(dem|dsm)(?![a-z0-9])", "수치표고모델"),
    (r"(?<![a-z0-9])lidar(?![a-z0-9])", "라이다"),
    (r"(?<![a-z0-9])(db|database)(?![a-z0-9])", "데이터베이스"),
    (r"(?<![a-z0-9])(cnn|deep\s*learning)(?![a-z0-9])", "딥러닝"),
    (r"(?<![a-z0-9])segmentation(?![a-z0-9])", "세그멘테이션"),
    (r"(?<![a-z0-9])(super\s*resolution|sr영상)(?![a-z0-9])", "초해상화"),
    (r"(?<![a-z0-9])object\s*detection(?![a-z0-9])", "객체탐지"),
    (r"(?<![a-z0-9])digital\s*twin(?![a-z0-9])", "디지털트윈"),
    (r"(?<![a-z0-9])dataset(?![a-z0-9])", "데이터셋"),
    # --- 카탈로그 브랜드 (S: 제품·브랜드 exact) --------------------------
    (r"(?<![a-z0-9])dabeeo(?![a-z0-9])", "다비오"),
    (r"(?<![a-z0-9])earth\s*eye(?![a-z0-9])", "어스아이"),
    (r"(?<![a-z0-9])eartheye(?![a-z0-9])", "어스아이"),
    (r"(?<![a-z0-9])geo[\s-]*studio(?![a-z0-9])", "지오스튜디오"),
    (r"(?<![a-z0-9])geo[\s-]*int(elligence)?(?![a-z0-9])", "지오인텔리전스"),
    # --- 카탈로그 기술 용어 -----------------------------------------------
    (r"(?<![a-z0-9])(3d\s*reconstruction|2\.5d)(?![a-z0-9])", "3차원재구축"),
    (r"(?<![a-z0-9])(mum[\s-]*t|manned[\s-]*unmanned)(?![a-z0-9])", "유무인복합"),
    (r"(?<![a-z0-9])(k[\s-]*)?uam(?![a-z0-9])", "도심항공교통"),
    (r"(?<![a-z0-9])urban\s*air\s*mobility(?![a-z0-9])", "도심항공교통"),
    (r"(?<![a-z0-9])vertiport(?![a-z0-9])", "버티포트"),
    (r"(?<![a-z0-9])k[\s-]*leo(?![a-z0-9])", "저궤도위성"),
    (r"(?<![a-z0-9])(ndvi|evi)(?![a-z0-9])", "식생지수"),
    (r"(?<![a-z0-9])(pan[\s-]*sharpening)(?![a-z0-9])", "영상융합"),
    (r"(?<![a-z0-9])redd\+?(?![a-z0-9])", "산림탄소"),
    (r"(?<![a-z0-9])(koica|edcf)(?![a-z0-9])", "oda"),
    (r"(?<![a-z0-9])(kompsat|komsat|아리랑위성)(?![a-z0-9])", "위성영상"),
    (r"(?<![a-z0-9])hd\s*map(?![a-z0-9])", "정밀도로지도"),
    (r"(?<![a-z0-9])(node[\s-]*link)(?![a-z0-9])", "노드링크"),
    (r"(?<![a-z0-9])(ship|vessel)\s*detection(?![a-z0-9])", "선박탐지"),
    (r"(?<![a-z0-9])illegal\s*(building|construction)(?![a-z0-9])", "불법건축물"),
    (r"(?<![a-z0-9])deforestation(?![a-z0-9])", "산림황폐화"),
    (r"(?<![a-z0-9])(oil\s*palm|plantation)(?![a-z0-9])", "플랜테이션"),
    (r"(?<![a-z0-9])(labeling|labelling|annotation)(?![a-z0-9])", "데이터라벨링"),
    (r"(?<![a-z0-9])battle\s*field(?![a-z0-9])", "전장환경"),
    (r"(?<![a-z0-9])lod\s*\d?(\.\d)?(?![a-z0-9])", "lod"),
]

# 한글 표기 변형 → 대표어 (공백 제거된 compact 문자열에 적용)
_HANGUL_CANON: List[Tuple[str, str]] = [
    (r"객체(식별|인식|검출)", "객체탐지"),
    (r"초해상도|슈퍼레졸루션|초고해상도복원", "초해상화"),
    (r"오쏘포토|오쏘영상|정사영상제작", "정사영상"),
    (r"수치지도", "수치지형도"),
    (r"항공영상|항공측량영상|항측영상", "항공사진"),
    (r"위성사진|위성이미지", "위성영상"),
    (r"데이터세트", "데이터셋"),
    (r"학습용데이터|훈련데이터|학습데이터셋|ai학습데이터", "학습데이터"),
    (r"무인항공기|무인비행장치|무인기(?!술)", "드론"),
    (r"지리정보시스템|지리정보체계", "지리정보"),
    (r"기계학습|머신러닝", "딥러닝"),
    (r"영상분할", "세그멘테이션"),
    (r"인공위성", "위성"),
    (r"디지털쌍둥이", "디지털트윈"),
    (r"영상판독", "판독"),
    (r"데이터베이스구축|디비구축", "데이터베이스구축"),
    # --- 카탈로그 §9 동의어 그룹 (S01~S28) --------------------------------
    (r"위성자료", "위성영상"),
    (r"3차원복원|3차원모델링|3d모델링|3d재구축|3d재구성|실사기반3d|메쉬", "3차원재구축"),
    (r"3차원국토공간정보|3차원공간정보|3d공간정보", "3차원공간정보"),
    (r"디지털트윈국토", "디지털트윈"),
    (r"디지털맵|전자지도|지도데이터|기본도|지형도(?!화)", "수치지형도"),
    (r"표준노드링크|노드링크|링크노드|도로망데이터", "노드링크"),
    (r"에이치디맵|정밀도로지도", "정밀도로지도"),
    (r"레이더영상|영상레이더", "합성개구레이더"),
    (r"함정탐지|어선탐지|불법조업선박", "선박탐지"),
    (r"위반건축물|무허가건축물|불법증축", "불법건축물"),
    (r"산림훼손|임상변화|산림변화", "산림황폐화"),
    (r"죽은나무|피해목|쇠약목|구상나무", "고사목"),
    (r"팜오일|오일팜|팜농장|야자농장|플렌테이션", "플랜테이션"),
    (r"도심항공모빌리티|케이유에이엠", "도심항공교통"),
    (r"탄소저장량|탄소상쇄", "탄소흡수량"),
    (r"3d전장|3차원전장|전장가시화|전장정보", "전장환경"),
    (r"유·?무인복합전투체계|유무인협업|유무인복합", "유무인복합"),
    (r"국공유지|국유지|국·?공유재산|공유재산", "국유재산"),
    (r"해상도향상|화질개선|업스케일링", "초해상화"),
    (r"어노테이션|데이터라벨링|라벨링", "데이터라벨링"),
    (r"다중센서융합|이종영상융합|영상융합|다중해상도융합", "영상융합"),
    (r"현황조사|실태조사", "실태조사"),
    (r"시계열분석|시계열변화", "시계열"),
    (r"수목탐지|개체목탐지|개체목", "개체목"),
    (r"의미분할|객체분할|영역분할|인스턴스세그멘테이션|시맨틱세그멘테이션", "세그멘테이션"),
    (r"플랫폼구축|서비스구축", "플랫폼구축"),   # 아래에서 다시 분해
    (r"플랫폼구축", "플랫폼 구축"),
]

_YEAR_PATTERNS = [
    r"^\s*\d{4}\s*년도?\s*",
    r"\d{4}\s*년도?\s*",
    r"['’]\s*\d{2}\s*년도?\s*",
    r"제?\s*\d+\s*차\s*",
    r"\d+\s*단계",
    r"pc\s*\d+",
]


@dataclass
class Normalized:
    raw: str
    spaced: str      # 정규화 + 공백 보존 (하드제외/범위 판정용)
    compact: str     # 공백 제거 (긍정 키워드 매칭용)


def normalize(text: str) -> Normalized:
    """L0: 표기 정규화. compact/spaced 두 벌을 만들어 용도에 따라 쓴다."""
    raw = text or ""
    s = unicodedata.normalize("NFKC", raw)
    s = s.lower()
    for ch in _BRACKETS + _PUNCT:
        s = s.replace(ch, " ")
    for pat in _YEAR_PATTERNS:
        s = re.sub(pat, " ", s)
    for pat, rep in _LATIN_CANON:
        s = re.sub(pat, rep, s)
    s = re.sub(r"\s+", " ", s).strip()
    spaced = s

    compact = re.sub(r"\s+", "", s)
    for pat, rep in _HANGUL_CANON:
        compact = re.sub(pat, rep, compact)
    compact = re.sub(r"\s+", "", compact)
    return Normalized(raw=raw, spaced=spaced, compact=compact)


# =============================================================================
# 4. 매칭 유틸 (L3 가드 포함)
# =============================================================================

def _spans(pattern: str, text: str) -> List[Tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def _keyword_hit(keyword: str, compact: str) -> bool:
    """키워드가 '올바른 의미'로 등장하는지. 모든 출현이 금지 컨텍스트 안이면 False."""
    occ = _spans(re.escape(keyword), compact)
    if not occ:
        return False
    guards = GUARDS.get(keyword)
    if not guards:
        return True
    gspans: List[Tuple[int, int]] = []
    for g in guards:
        gspans.extend(_spans(g, compact))
    if not gspans:
        return True
    for s, e in occ:
        if not any(gs <= s and e <= ge for gs, ge in gspans):
            return True
    return False


def _drop_contained(matched: Sequence[str]) -> List[str]:
    """'군사지도'가 잡혔으면 '지도'는 중복 가산하지 않는다."""
    out = []
    for kw in matched:
        if any(kw != other and kw in other for other in matched):
            continue
        out.append(kw)
    return out


def _first_regex_hit(patterns: Iterable[str], text: str) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0).strip()
    return None


# =============================================================================
# 5. 스코어 결과
# =============================================================================

@dataclass
class ScoreResult:
    score: int = 0
    tier: str = TIER_DROP
    matched: Dict[str, List[str]] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    hurdle: bool = False
    cooccur: bool = False
    excluded: bool = False
    exclude_reason: str = ""
    out_of_scope: bool = False
    eligibility: List[str] = field(default_factory=list)  # 사람 검토 필요 자격
    matched_project: Optional[str] = None  # 실제 제안/투찰 이력과 매칭된 경우 그 사업명

    # 기존 호출부 `score, reasons = calculate_score(title)` 하위호환
    def __iter__(self):
        return iter((self.score, self.reasons))

    @property
    def reason_text(self) -> str:
        return " / ".join(self.reasons)

    @property
    def matched_flat(self) -> List[str]:
        out: List[str] = []
        for group in ("brand", "core", "mid", "adjacent", "weak"):
            out.extend(self.matched.get(group, []))
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "tier": self.tier,
            "matched": self.matched,
            "reasons": self.reasons,
            "hurdle": self.hurdle,
            "cooccur": self.cooccur,
            "excluded": self.excluded,
            "exclude_reason": self.exclude_reason,
            "out_of_scope": self.out_of_scope,
            "eligibility": self.eligibility,
        }


# =============================================================================
# 6. calculate_score — 레이어드 판정
# =============================================================================

def _score_group(table: Dict[str, int], compact: str) -> Tuple[int, List[str]]:
    hits = [kw for kw in table if _keyword_hit(kw, compact)]
    hits = _drop_contained(hits)
    total = sum(table[kw] for kw in hits)
    return total, sorted(hits, key=lambda k: -table[k])


def calculate_score(
    title: str,
    agency: str = "",
    item: Optional[Dict[str, Any]] = None,
) -> ScoreResult:
    """공고명(+발주기관, +원본 item)을 받아 점수/등급/근거를 반환한다."""
    item = item or {}
    res = ScoreResult()
    n = normalize(title)
    agency_n = normalize(agency or "")

    # ---- L0.5 실제 제안/투찰 이력 매칭 → 다른 판정보다 최우선으로 '상' 고정 --
    won = _match_won_project(n.compact)
    if won:
        res.score = 100
        res.tier = TIER_HIGH
        res.hurdle = True
        res.cooccur = True
        res.matched = {"core": won["hits"]}
        res.matched_project = won["name"]
        res.reasons.append(f"과거 실제 제안/투찰 이력과 동일 유형('{won['name']}') → 상 고정")
        return res

    # ---- L1 범위 판정 -----------------------------------------------------
    oos = _first_regex_hit(OUT_OF_SCOPE_PATTERNS, n.spaced)
    if oos:
        res.out_of_scope = True
        res.excluded = True
        res.exclude_reason = f"스코어링 대상 아님(별도 경로: '{oos}')"
        res.reasons.append(res.exclude_reason)
        res.tier = TIER_DROP
        return res

    # ---- L3 가드 적용 후 긍정 키워드 수집 (하드제외 구제 판단에 필요) -------
    brand_score, brand_hits = _score_group(BRAND_WEIGHT_KEYWORDS, n.compact)
    core_score, core_hits = _score_group(HIGH_WEIGHT_KEYWORDS, n.compact)
    mid_score, mid_hits = _score_group(MID_WEIGHT_KEYWORDS, n.compact)
    adj_score, adj_hits = _score_group(ADJACENT_KEYWORDS, n.compact)
    weak_score, weak_hits = _score_group(WEAK_KEYWORDS, n.compact)

    domain_cores = [k for k in (brand_hits + core_hits) if k in DOMAIN_FAMILY]
    tech = [k for k in (core_hits + mid_hits) if k in TECH_FAMILY]

    # ---- L2 하드 제외 ------------------------------------------------------
    neg = _first_regex_hit(NEGATIVE_KEYWORDS, n.spaced)
    if neg:
        res.excluded = True
        res.exclude_reason = f"하드제외 키워드 '{neg}'"
        res.reasons.append(res.exclude_reason)
        res.tier = TIER_DROP
        return res

    # ---- L2b 소프트 제외 + 구제 -------------------------------------------
    penalty = 0
    soft = _first_regex_hit(SOFT_EXCLUDE_KEYWORDS, n.spaced)
    if soft:
        # 구제 조건: 도메인 코어 2개 이상, 또는 도메인 코어 1개 + 기술 동시출현
        rescued = bool(
            re.search(r"용역|사업|구축|개발|제작|고도화|운영", n.spaced)
            and (len(domain_cores) >= 2 or (domain_cores and tech))
        )
        if not rescued:
            res.excluded = True
            res.exclude_reason = f"소프트제외 키워드 '{soft}' (구제조건 미충족)"
            res.reasons.append(res.exclude_reason)
            res.tier = TIER_DROP
            return res
        penalty += SOFT_EXCLUDE_PENALTY
        res.reasons.append(
            f"소프트제외 '{soft}' → 도메인코어 {len(domain_cores)}개"
            f"{'+기술' if tech else ''}로 구제, {SOFT_EXCLUDE_PENALTY}점"
        )

    # ---- L2c 감점 ---------------------------------------------------------
    for pat, pen in PENALTY_KEYWORDS.items():
        m = re.search(pat, n.spaced)
        if m:
            penalty += pen
            res.reasons.append(f"감점 키워드 '{m.group(0)}' {pen}점")

    # ---- L4 가산 ----------------------------------------------------------
    score = brand_score + core_score + mid_score + adj_score + weak_score
    if brand_hits:
        res.reasons.append(f"브랜드 +{brand_score} ({', '.join(brand_hits)})")
    if core_hits:
        res.reasons.append(f"코어 +{core_score} ({', '.join(core_hits)})")
    if mid_hits:
        res.reasons.append(f"미드 +{mid_score} ({', '.join(mid_hits)})")
    if adj_hits:
        res.reasons.append(f"인접 +{adj_score} ({', '.join(adj_hits)})")
    if weak_hits:
        res.reasons.append(f"약가중 +{weak_score} ({', '.join(weak_hits)})")

    # ---- L5 동시출현 보너스 ------------------------------------------------
    if domain_cores and tech:
        score += COOCCUR_BONUS
        res.cooccur = True
        res.reasons.append(
            f"동시출현 보너스 +{COOCCUR_BONUS} "
            f"(데이터/도메인 '{domain_cores[0]}' × 기술 '{tech[0]}')"
        )

    # ---- L6 컨텍스트: 발주기관 --------------------------------------------
    agency_hay = f"{agency_n.compact}|{n.compact}"
    hit_agency = next((a for a in AGENCY_WHITELIST if a.replace(" ", "") in agency_hay), None)
    if hit_agency:
        score += AGENCY_BONUS
        res.reasons.append(f"발주기관 화이트리스트 +{AGENCY_BONUS} ({hit_agency})")

    # ---- L6 컨텍스트: 추정가격 / 분류 (필드명 미검증) ----------------------
    price = _to_int(item.get("presmptPrce") or item.get("asignBdgtAmt"))
    if price and 0 < price < PRICE_FLOOR:
        score += PRICE_FLOOR_PENALTY
        res.reasons.append(f"추정가격 {price:,}원(하한 미달) {PRICE_FLOOR_PENALTY}점")

    category = str(item.get("ntceKindNm") or item.get("bsnsDivNm") or "")
    if re.search(r"공사|물품|제조|시설", category):
        res.excluded = True
        res.exclude_reason = f"공고 분류 '{category}' (용역 아님)"
        res.reasons.append(res.exclude_reason)
        res.tier = TIER_DROP
        return res

    # ---- L6b 참가자격 게이트 (감점 아님 — 사람 검토 라우팅) ---------------
    hay = f"{n.spaced} {agency_n.spaced} {str(item.get('bidprcPsblIndstrytyNm') or '')}".lower()
    for pat, label in ELIGIBILITY_PATTERNS.items():
        if re.search(pat, hay):
            res.eligibility.append(label)
    if res.eligibility:
        res.reasons.append(
            "참가자격 확인 필요: " + ", ".join(res.eligibility) + " (카탈로그상 보유 근거 없음)"
        )

    score += penalty
    score = max(0, min(SCORE_CAP, score))
    res.score = score
    res.matched = {
        "brand": brand_hits,
        "core": core_hits,
        "mid": mid_hits,
        "adjacent": adj_hits,
        "weak": weak_hits,
    }

    # ---- L7 허들 + 등급 ---------------------------------------------------
    hurdle_hits = [
        k for k in (brand_hits + core_hits)
        if k in DOMAIN_FAMILY or k in HURDLE_EXTRA_FAMILY
    ]
    res.hurdle = bool(hurdle_hits)

    strong_domain = res.cooccur or len(domain_cores) >= 2

    if score < SCORE_MID_CUT:
        res.tier = TIER_DROP
        res.reasons.append(f"{SCORE_MID_CUT}점 미만 → 리포트 제외")
    elif score < SCORE_HIGH_CUT:
        res.tier = TIER_MID
    else:
        if res.hurdle and strong_domain:
            res.tier = TIER_HIGH
            res.reasons.append(f"허들 통과({hurdle_hits[0]}) + 도메인 강신호 → 상")
        else:
            res.tier = TIER_MID
            missing = "허들 키워드(위성·항공·드론·공간정보·시그니처)" if not res.hurdle \
                else "도메인 강신호(데이터·시그니처 코어 × 기술 동시출현, 또는 도메인 코어 2개)"
            res.reasons.append(f"{score}점이지만 {missing} 부족 → 중 강등")
    return res


def _to_int(v: Any) -> int:
    try:
        return int(float(str(v).replace(",", "").strip()))
    except Exception:
        return 0


# =============================================================================
# 7. DB
# =============================================================================

DDL = """
CREATE TABLE IF NOT EXISTS bids (
    bid_no        TEXT PRIMARY KEY,
    bid_name      TEXT NOT NULL,
    order_agency  TEXT,
    bid_date      TEXT,
    bid_url       TEXT,
    region        TEXT,
    score         INTEGER DEFAULT 0,
    tier          TEXT,
    matched       TEXT,
    reasons       TEXT,
    eligibility   TEXT,
    source        TEXT,
    rfp_file_url  TEXT,
    rfp_file_name TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_bids_created ON bids(created_at);
CREATE INDEX IF NOT EXISTS idx_bids_tier ON bids(tier);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """bids 테이블 생성. g2b_bot_email.py 가 기대하는 컬럼명을 그대로 맞춘다."""
    with _connect() as conn:
        conn.executescript(DDL)


def save_bids_to_db(bids: Sequence[Dict[str, Any]]) -> int:
    if not bids:
        return 0
    init_db()
    rows = [
        (
            b.get("bid_no", ""),
            b.get("bid_name", ""),
            b.get("order_agency", ""),
            b.get("bid_date", ""),
            b.get("bid_url", ""),
            b.get("region", ""),
            int(b.get("score", 0) or 0),
            b.get("tier", ""),
            json.dumps(b.get("matched", []), ensure_ascii=False),
            json.dumps(b.get("reasons", []), ensure_ascii=False),
            json.dumps(b.get("eligibility", []), ensure_ascii=False),
            b.get("source", "G2B"),
            b.get("rfp_file_url", ""),
            b.get("rfp_file_name", ""),
        )
        for b in bids
        if b.get("bid_no")
    ]
    with _connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO bids
               (bid_no, bid_name, order_agency, bid_date, bid_url, region,
                score, tier, matched, reasons, eligibility, source,
                rfp_file_url, rfp_file_name)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return len(rows)


def filter_new_bids(bids: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """배치 1회 질의로 신규 공고만 골라낸다 (건당 SELECT 루프 제거)."""
    if not bids:
        return []
    init_db()
    nos = [b["bid_no"] for b in bids if b.get("bid_no")]
    known: set = set()
    with _connect() as conn:
        for i in range(0, len(nos), 500):
            chunk = nos[i:i + 500]
            q = ",".join("?" * len(chunk))
            known.update(
                r[0] for r in conn.execute(
                    f"SELECT bid_no FROM bids WHERE bid_no IN ({q})", chunk
                )
            )
    return [b for b in bids if b.get("bid_no") and b["bid_no"] not in known]


# =============================================================================
# 8. G2B 수집
# =============================================================================

def _session():
    if requests is None:
        raise RuntimeError("requests 미설치")
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"Accept": "application/json", "User-Agent": "dabeeo-bid-bot/2.0"})
    return s


def _api_key() -> str:
    key = (
        os.environ.get("G2B_API_KEY")
        or os.environ.get("SERVICE_KEY")
        or os.environ.get("G2B_SERVICE_KEY")
        or ""
    )
    # 인코딩 키가 들어와도 동작하도록 1회 디코드
    return urllib.parse.unquote(key)


def _normalize_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """items 가 list / {'item': [...]} / {'item': {...}} / '' 인 모든 경우를 흡수."""
    body = (payload or {}).get("response", {}).get("body", {}) or {}
    items = body.get("items")
    if not items:
        return []
    if isinstance(items, dict):
        inner = items.get("item")
        if inner is None:
            return []
        return inner if isinstance(inner, list) else [inner]
    if isinstance(items, list):
        return [i for i in items if isinstance(i, dict)]
    return []


def _kst_window(days: int = 3) -> Tuple[str, str]:
    now = datetime.now(KST)
    bgn = (now - timedelta(days=days)).strftime("%Y%m%d0000")
    end = now.strftime("%Y%m%d%H%M")
    return bgn, end


def fetch_g2b_bids(
    keywords: Optional[Sequence[str]] = None,
    days: int = 3,
    operation: str = G2B_SERVC_OP,
    min_score: int = SCORE_MID_CUT,
) -> List[Dict[str, Any]]:
    """시드 키워드별로 bidNtceNm 필터를 걸어 다중 질의 + 페이지네이션 수집."""
    init_db()
    key = _api_key()
    if not key:
        print("[WARN] G2B_API_KEY / SERVICE_KEY 환경변수가 없습니다.")
        return []

    keywords = list(keywords or KEYWORDS)
    bgn, end = _kst_window(days)
    url = f"{G2B_BASE}/{operation}"
    sess = _session()

    seen: set = set()
    results: List[Dict[str, Any]] = []

    for kw in keywords:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "serviceKey": key,
                "type": "json",
                "numOfRows": str(NUM_OF_ROWS),
                "pageNo": str(page),
                "inqryDiv": "1",            # 1=공고게시일시 기준
                "inqryBgnDt": bgn,
                "inqryEndDt": end,
                "bidNtceNm": kw,
                "bidClseExcpYn": "Y",       # 마감 공고 제외
            }
            try:
                r = sess.get(url, params=params, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                try:
                    payload = r.json()
                except ValueError:
                    print(f"[API ERROR] '{kw}' p{page}: 비 JSON 응답 → {r.text[:180]}")
                    break
            except Exception as e:
                print(f"[API ERROR] '{kw}' p{page}: {e}")
                break

            header = (payload.get("response", {}) or {}).get("header", {}) or {}
            code = str(header.get("resultCode", "00"))
            if code not in ("00", "0"):
                print(f"[API WARN] '{kw}' resultCode={code} msg={header.get('resultMsg')}")
                break

            items = _normalize_items(payload)
            if not items:
                break

            for it in items:
                bid_no = str(it.get("bidNtceNo") or "").strip()
                ord_no = str(it.get("bidNtceOrd") or "").strip()
                uid = f"{bid_no}-{ord_no}" if ord_no else bid_no
                if not uid or uid in seen:
                    continue
                seen.add(uid)

                title = str(it.get("bidNtceNm") or "")
                agency = str(it.get("ntceInsttNm") or it.get("dminsttNm") or "미지정 기관")
                sr = calculate_score(title, agency=agency, item=it)
                print(f"[검토] {sr.score:3d} {sr.tier} | {title} | {sr.reason_text}")

                if sr.tier in (TIER_DROP,) or sr.score < min_score:
                    continue

                results.append({
                    "bid_no": uid,
                    "bid_name": title,
                    "order_agency": agency,
                    "bid_date": it.get("bidClseDt") or "진행중",
                    "bid_url": it.get("bidNtceDtlUrl") or it.get("bidNtceUrl") or "",
                    "region": it.get("prtcLmtRgnNm") or "전국",
                    "score": sr.score,
                    "tier": sr.tier,
                    "matched": sr.matched_flat,
                    "reasons": sr.reasons,
                    "eligibility": sr.eligibility,
                    "matched_project": sr.matched_project,
                    "source": "G2B",
                })

            total = _to_int(((payload.get("response", {}) or {}).get("body", {}) or {}).get("totalCount"))
            if page * NUM_OF_ROWS >= total:
                break

    results.sort(key=lambda b: (-b["score"], b["bid_name"]))
    print(f"--- 수집 {len(seen)}건 / 통과 {len(results)}건 ---")
    return results


# 기존 호출부(g2b_bot_email.py) 하위호환 별칭
def fetch_g2b_servc_bids() -> List[Dict[str, Any]]:
    return fetch_g2b_bids()


# =============================================================================
# 9. D2B(국방전자조달) 수집 — 방위사업청_군수품조달정보 입찰공고_GW
# =============================================================================
# 응답이 표준 XML(<response><header>.../<body>...)이라 XML로 파싱한다.
# g2b_bot_email.py 는 이 함수를 `try: from dabeeo_bid_master import fetch_d2b_bids`
# 로 옵셔널 임포트하므로, 존재만 하면 자동으로 파이프라인에 합류한다.

def _d2b_api_key() -> str:
    key = os.environ.get("D2B_API_KEY") or ""
    return urllib.parse.unquote(key)


def _d2b_date_window(days: int = 3) -> Tuple[str, str]:
    """D2B는 시간 없이 YYYYMMDD 8자리 날짜만 받는다 (G2B의 분단위 포맷과 다름)."""
    now = datetime.now(KST)
    bgn = (now - timedelta(days=days)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    return bgn, end


def _d2b_text(el: Optional["ET.Element"], tag: str) -> str:
    if el is None:
        return ""
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def fetch_d2b_bids(days: int = 3, min_score: int = SCORE_MID_CUT) -> List[Dict[str, Any]]:
    """국내 경쟁입찰공고 목록(getDmstcCmpetBidPblancList)을 공고일자 구간으로 수집.

    D2B는 상세페이지 직접 링크를 제공하지 않으므로(README FAQ 참고) bid_url은
    비워두고, region 필드도 API가 제공하지 않아 채우지 않는다 — 이메일 템플릿의
    기본값('국방전용/전국')이 자동으로 적용된다.
    """
    key = _d2b_api_key()
    if not key:
        print("[WARN] D2B_API_KEY 환경변수가 없습니다.")
        return []

    bgn, end = _d2b_date_window(days)
    url = f"{D2B_BASE}/{D2B_DMSTC_LIST_OP}"
    sess = _session()

    seen: set = set()
    results: List[Dict[str, Any]] = []

    for page in range(1, D2B_MAX_PAGES + 1):
        params = {
            "serviceKey": key,
            "pageNo": str(page),
            "numOfRows": str(D2B_NUM_OF_ROWS),
            "anmtDateBegin": bgn,
            "anmtDateEnd": end,
        }
        try:
            r = sess.get(url, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            print(f"[D2B API ERROR] p{page}: {e}")
            break

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            print(f"[D2B API ERROR] p{page}: XML 파싱 실패 → {r.text[:180]}")
            break

        header = root.find("header")
        code = _d2b_text(header, "resultCode") or "00"
        if code not in ("00", "0"):
            print(f"[D2B API WARN] resultCode={code} msg={_d2b_text(header, 'resultMsg')}")
            break

        body = root.find("body")
        items = body.findall("items/item") if body is not None else []
        if not items:
            break

        for it in items:
            pblanc_no = _d2b_text(it, "pblancNo")
            pblanc_odr = _d2b_text(it, "pblancOdr")
            uid = f"{pblanc_no}-{pblanc_odr}" if pblanc_odr else pblanc_no
            if not uid or uid in seen:
                continue
            seen.add(uid)

            title = _d2b_text(it, "bidNm")
            agency = _d2b_text(it, "ornt") or "미지정 기관"
            sr = calculate_score(title, agency=agency)
            print(f"[D2B 검토] {sr.score:3d} {sr.tier} | {title} | {sr.reason_text}")

            if sr.tier in (TIER_DROP,) or sr.score < min_score:
                continue

            # 입찰서제출마감일 > 개찰일시 순으로 표시용 마감일 결정
            deadline = (
                _d2b_text(it, "biddocPresentnClosDt")
                or _d2b_text(it, "opengDt")
                or "진행중"
            )

            # D2B 사이트 검색창에 붙여넣을 '공고번호' 후보 — 어느 쪽이 실제로 검색되는지
            # 아직 확인 전이라 g2bPblancNo(-차수)를 1순위, dcsNo(판단번호)를 2순위로 둔다.
            g2b_no = _d2b_text(it, "g2bPblancNo")
            g2b_odr = _d2b_text(it, "g2bPblancOdr")
            dcs_no = _d2b_text(it, "dcsNo")
            search_no = (
                (f"{g2b_no}-{g2b_odr}" if g2b_odr else g2b_no) if g2b_no
                else (dcs_no or uid)
            )

            results.append({
                "bid_no": search_no,
                "bid_name": title,
                "order_agency": agency,
                "bid_date": deadline,
                "score": sr.score,
                "tier": sr.tier,
                "matched": sr.matched_flat,
                "reasons": sr.reasons,
                "eligibility": sr.eligibility,
                "matched_project": sr.matched_project,
                "source": "D2B",
                "d2b_dcs_no": dcs_no,        # 검증용: 판단번호(구매요청번호)
                "d2b_internal_no": uid,       # 검증용: D2B 내부 관리번호(기존값)
            })

        total = _to_int(_d2b_text(body, "totalCount"))
        if page * D2B_NUM_OF_ROWS >= total:
            break

    results.sort(key=lambda b: (-b["score"], b["bid_name"]))
    print(f"--- D2B 수집 {len(seen)}건 / 통과 {len(results)}건 ---")
    return results


def escape(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


if __name__ == "__main__":
    for t in [
        "위성영상 AI 분석 기반 멀티영상 분석 플랫폼 고도화 사업(협상)",
        "위성방송 수신 안테나 설치 공사",
    ]:
        r = calculate_score(t)
        print(f"{r.score:3d} {r.tier} | {t}\n     {r.reason_text}")
