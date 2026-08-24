# -*- coding: utf-8 -*-
"""
test_scoring.py — 라벨 데이터로 스코어링 규칙을 회귀 검증한다.
실행: python3 test_scoring.py     (표준 unittest 로도 동작)

판정 기준
  TIER-A : tier == '상'  또는 (tier == '중' and score >= 35)   ← "상 또는 high 중"
  TIER-B : tier != '상'  and tier != '제외'  (= '중'에 안착)
  TIER-B-감리 : tier == '제외' (다비오 스코프 아님. 근거는 가이드 문서 참조)
  OUT-OF-SCOPE : tier == '제외'
  TIER-C : tier == '제외'
"""
import unittest

from dabeeo_bid_master import calculate_score, TIER_HIGH, TIER_MID, TIER_DROP

HIGH_CUT_MID = 35  # 'high 중' 하한

TIER_A = [
    "도미니카(공) ICT기반 국립공원 기후변화 모니터링 역량 고도화 사업 PC1(시스템구축) 용역",
    "초소형위성체계 활용시스템 예비설계 및 활용기술 개발 용역",
    "KSIS 데이터 기반 초소형위성 활용시스템 개발 및 시험 용역",
    "파주시 정사영상 제작 사업",
    "군사지도 구축 사업",
    "군수지도 제작 용역",
    "초소형체계 민 임무연동체 위성영상시스템 개발",
    "위성영상, AI 기반 '25년 벼 관개현황, 재배지 탐지 기술 개발",
    "위성영상 AI 분석 기반 멀티영상 분석 플랫폼 고도화 사업(협상)",
    "국토위성 주요상태 모니터링 기술 개발",
    "위성정보 빅데이터 AI 학습데이터 구축",
    "항공사진 기반 변화이력 추적 자동화 연구 2차",
    "상용위성 영상정보 활용방안 연구",
    "국유지 변화탐지 분석 시스템 개발",
    "k-water 드론 촬영 용역",
    "에이전틱 AI 산림서비스 요소기술 식별 및 영상 품질 관리 자동화",
    "산림청 전용 산림위성영상 분류 및 품질관리 자동화 서비스 구축 사업",
    "해양경찰청 MDA 5차 사업",
    "해경 위성활용시스템 사업",
    "(25G043-H) AI 객체식별 기반 지리공간분석 기술 실증",
    "2025년도 대전광역시 일원 항공사진 판독용역",
    "2024년도 대전광역시 일원 항공사진 판독용역",
    "한국도로공사 AI·위성 기반 정보 고도화 연구",
    "AI·위성 기반 북한도로 인프라 고도화 R&D",
    "통일부 북한 위성분석 연구용역",
    "콜롬비아 ODA 지적정보 DB 구축 용역",
    "위성기반 선박분류 체계 개선 및 데이터셋 구축",
    "위성영상 인공지능 학습데이터 저작도구 개선",
    "해양 모니터링 AI 학습 데이터셋 구축을 위한 위성영상 선정 및 전처리 사업",
    "위성 정보 빅데이터 AI 학습 데이터 구축 사업",
    "경상북도 지능공간정보 플랫폼 구축 용역",
    "세종 공간정보 통합 플랫폼 구축 사업(3단계)",
    # 소프트제외 구제(rescue) 검증용
    "위성영상 기반 공간정보 구축 및 시스템 유지관리 용역",
]

# 카탈로그(§12 U1~U14)가 뒷받침하는 '과소반영 역량' — 현행 키워드셋이 놓치던 유형.
# 기대: 제외되지 않고 최소 '중', 도메인 신호가 충분하면 '상'.
TIER_U = [
    "3차원 국토공간정보 LOD 구축 사업",                        # U1
    "디지털트윈국토 시범사업 3차원 건물모델 제작",             # U1
    "정밀도로지도 표준노드링크 갱신 용역",                     # U2
    "노면표시 및 차선 조사 AI 자동화 용역",                    # U2
    "AI 학습용 데이터 라벨링 및 데이터 검수 용역",             # U3
    "K-UAM 회랑 공역 3D 지도 구축",                            # U4
    "K-LEO 저궤도위성 산업협력 위성정보활용 실증",             # U4
    "산림 탄소흡수량 산정 및 탄소배출권 분석 연구",            # U5
    "국유재산 무단점유 실태조사(위성영상 활용)",               # U6
    "위반건축물 항공사진 판독 용역",                           # U7
    "SAR 기반 불법조업 선박탐지 체계 개발",                    # U8
    "급경사지 산사태 위험지역 원격 진단 연구",                 # U9
    "KOICA 개도국 공간정보 ODA 구축 용역",                     # U10
    "위성영상 초해상화 및 영상융합 품질개선 용역",             # U11
    "개체목 단위 생육 관측 및 식생지수 분석 용역",             # U12
    "국방 AI 유무인복합 전장환경 학습데이터 구축 R&D",         # U13
    "상용위성영상 아카이브 확보 및 영상 수집 용역",            # U14
    "dabeeo Eartheye 기반 변화탐지 분석 용역",                 # 브랜드
]

TIER_B = [
    "비전AI 기반 지능형 문화관람 서비스 구축",
    "2026년 지능형 멀티 문화정보 큐레이팅봇 구축",
    "디지털 트윈 기반 통합관제 시스템 구축",
    "글로벌축제 QR.here 구축",
]

TIER_B_DROP = [
    # 감리는 설계·시공 감독 업무로 다비오 수행 스코프가 아니다 → -35 감점, 제외 안착
    "도미니카(공) ODA 감리용역",
]

OUT_OF_SCOPE = [
    "2026년 AI응용제품 신속상용화 지원 프로그램 공모",
    "방산 중소기업 수출길 지원사업 참여기업 모집 공고",
    "선도연구기관(국방AI혁신랩) 지정 공모",
    "KSP 민간제안 사업 수요조사",
    "미래 신안보 혁신기업 지정 계획 공고",
    "UNOPS Long Term Agreement (LTA) for geospatial services",
    "NATO NSPA RFI - satellite imagery analytics",
    "티맵모빌리티 본사업 제안",
]

TIER_C = [
    "청사 외벽 도장 공사",
    "2026년 구내식당 급식 위탁 운영 용역",
    "본관 청사 청소 용역",
    "무인경비 시스템 유지관리 용역",
    "위성방송 수신 안테나 설치 공사",
    "위성통신 회선 임차 용역",
    "청사 위성TV 수신설비 유지보수",
    "위성 DMB 수신기 임대",
    "위성항법 기반 차량 관제 단말기 구매",
    "학교 학습지도 도우미 지원 인력 운영",
    "산림 지도점검 및 안전관리 용역",
    "생활체육 지도사 배치 사업",
    "지도 교사 대상 연수 프로그램 운영",
    "홍보영상 제작 용역",
    "회의실 영상장비 구매 설치",
    "CCTV 통합관제센터 영상정보처리기기 구매",
    "영상회의 시스템 구축 용역",
    "드론 기체 구매(교육용)",
    "드론 조종 자격 취득 교육 과정 운영",
    "드론축구 대회 행사대행 용역",
    "무인기 방제 약제 구매",
    "도서관 유휴공간 리모델링 공사",
    "사무공간 개선 및 가구 납품",
    "서버 및 스토리지 하드웨어 납품",
    "노트북 등 정보화기기 임대",
    "2026년 기관 소식지 인쇄 및 발송",
    "개관 기념 행사 대행 용역",
    "정보시스템 유지관리 단독 용역(연간)",
    "업무용 차량 임차 및 보험 가입",
    "상수도 관로 정비 공사 감리 용역",
    "직원 대상 AI 활용 역량강화 교육 연수",
    "공간정보 관련 서적 인쇄 납품",
    "체육관 공간 리모델링 및 방수 공사",
    # --- 카탈로그 §10 동형이의어 함정 (신규 추가 키워드가 만들 수 있는 오탐) ---
    "계량기 판독 검침 대행 용역",              # H07 판독
    "지문판독기 및 카드판독기 납품",           # H07
    "누수탐지 및 관로 진단 용역",              # H06 탐지
    "지하시설물 탐사(탐지) 용역",              # H06
    "침입탐지시스템(IDS) 도입",                # H06
    "3D 프린터 및 소재 구매",                  # H12 3D
    "3D 애니메이션 홍보 콘텐츠 제작",          # H12
    "역사 승강장(플랫폼) 안전문 보수 공사",    # H13 플랫폼
    "라벨프린터 및 라벨지 구매",               # H24 라벨링
    "탄소섬유 소재 납품",                      # H20 탄소
    "트윈타워 관리동 청소 용역",               # H18 트윈
    "방송스튜디오 음향설비 구축",              # H19 스튜디오
    "숲가꾸기 및 임도 개설 산림사업",          # H09 산림
    "항만 준설 및 방파제 보수 공사",           # H10 해양
    "실내체육관 바닥재 교체 공사",             # H05 실내
    "군 급식 및 피복 조달",                    # H11 국방
    "기상관측장비(우량계) 구매 설치",          # H08 관측
    "평생학습관 학습교재 구매",                # H15 학습
    "조직 변화관리 컨설팅 용역",               # H16 변화
    "서버 클러스터 GPU 노드 증설",             # H17 노드
    "정사(감사) 업무 지원 인력 운영",          # H22 정사
]


class TestTierA(unittest.TestCase):
    def test_tier_a(self):
        fails = []
        for t in TIER_A:
            r = calculate_score(t)
            ok = r.tier == TIER_HIGH or (r.tier == TIER_MID and r.score >= HIGH_CUT_MID)
            if not ok:
                fails.append(f"  [A] {r.tier}/{r.score:3d} {t}\n        {r.reason_text}")
        self.assertFalse(fails, "TIER-A 실패:\n" + "\n".join(fails))


class TestTierU(unittest.TestCase):
    """카탈로그 기반 과소반영 역량 — 제외되면 실패."""

    def test_under_served_not_dropped(self):
        fails = []
        for t in TIER_U:
            r = calculate_score(t)
            if r.tier == TIER_DROP:
                fails.append(f"  [U] {r.tier}/{r.score:3d} {t}\n        {r.reason_text}")
        self.assertFalse(fails, "TIER-U(과소반영 역량) 실패:\n" + "\n".join(fails))


class TestEligibility(unittest.TestCase):
    def test_eligibility_flag_routes_not_penalizes(self):
        r = calculate_score(
            "공간정보 구축 용역(공간정보사업자 등록 및 GS인증 보유 업체 제한)"
        )
        self.assertIn("공간정보사업자 등록", r.eligibility)
        self.assertIn("GS인증", r.eligibility)
        # 자격 플래그는 감점이 아니라 사람 검토 라우팅이어야 한다
        self.assertNotEqual(r.tier, TIER_DROP)

    def test_no_flag_when_absent(self):
        self.assertEqual(calculate_score("위성영상 변화탐지 용역").eligibility, [])


class TestTierB(unittest.TestCase):
    def test_tier_b_mid(self):
        fails = []
        for t in TIER_B:
            r = calculate_score(t)
            if r.tier != TIER_MID:
                fails.append(f"  [B] {r.tier}/{r.score:3d} {t}\n        {r.reason_text}")
        self.assertFalse(fails, "TIER-B 실패:\n" + "\n".join(fails))

    def test_tier_b_drop(self):
        for t in TIER_B_DROP:
            r = calculate_score(t)
            self.assertEqual(r.tier, TIER_DROP, f"{t} → {r.tier}/{r.score} {r.reason_text}")


class TestOutOfScope(unittest.TestCase):
    def test_out_of_scope(self):
        fails = []
        for t in OUT_OF_SCOPE:
            r = calculate_score(t)
            if r.tier != TIER_DROP:
                fails.append(f"  [O] {r.tier}/{r.score:3d} {t}\n        {r.reason_text}")
        self.assertFalse(fails, "OUT-OF-SCOPE 실패:\n" + "\n".join(fails))


class TestTierC(unittest.TestCase):
    def test_tier_c_noise_killed(self):
        fails = []
        for t in TIER_C:
            r = calculate_score(t)
            if r.tier != TIER_DROP:
                fails.append(f"  [C] {r.tier}/{r.score:3d} {t}\n        {r.reason_text}")
        self.assertFalse(fails, "TIER-C 실패:\n" + "\n".join(fails))


class TestGuards(unittest.TestCase):
    def test_homograph_guards(self):
        self.assertNotIn("위성", calculate_score("위성방송 중계 용역").matched.get("core", []))
        self.assertNotIn("지도", calculate_score("학습지도 보조 인력").matched.get("core", []))
        self.assertNotIn("영상", calculate_score("홍보영상 편집").matched.get("weak", []))
        self.assertIn("위성영상", calculate_score("위성 영상 분석").matched.get("core", []))

    def test_normalization_synonyms(self):
        a = calculate_score("orthophoto 제작 용역").matched.get("core", [])
        self.assertIn("정사영상", a)
        b = calculate_score("GIS 기반 객체 식별 시스템 구축").matched.get("core", [])
        self.assertIn("지리정보", b)
        self.assertIn("객체탐지", b)

    def test_legacy_unpack(self):
        score, reasons = calculate_score("위성영상 AI 분석")
        self.assertIsInstance(score, int)
        self.assertIsInstance(reasons, list)


def report():
    groups = [
        ("TIER-A (실제 입찰/수행)", TIER_A,
         lambda r: r.tier == TIER_HIGH or (r.tier == TIER_MID and r.score >= HIGH_CUT_MID)),
        ("TIER-U (카탈로그 과소반영 역량 → 제외 금지)", TIER_U,
         lambda r: r.tier != TIER_DROP),
        ("TIER-B (인접 → 중)", TIER_B, lambda r: r.tier == TIER_MID),
        ("TIER-B 감리 (→ 제외)", TIER_B_DROP, lambda r: r.tier == TIER_DROP),
        ("범위 밖 (공모/국제기구)", OUT_OF_SCOPE, lambda r: r.tier == TIER_DROP),
        ("TIER-C (노이즈 → 제외)", TIER_C, lambda r: r.tier == TIER_DROP),
    ]
    total_pass = total = 0
    for name, titles, ok_fn in groups:
        p = 0
        print(f"\n=== {name} ({len(titles)}건) ===")
        for t in titles:
            r = calculate_score(t)
            ok = ok_fn(r)
            p += ok
            print(f"  {'PASS' if ok else 'FAIL'} | {r.score:3d} {r.tier:2s} | {t}")
            if not ok:
                print(f"        └ {r.reason_text}")
        total_pass += p
        total += len(titles)
        print(f"  → {p}/{len(titles)} 통과")
    print(f"\n총계: {total_pass}/{total} 통과")
    return total_pass, total


if __name__ == "__main__":
    report()
    print()
    unittest.main(verbosity=1, exit=False)
