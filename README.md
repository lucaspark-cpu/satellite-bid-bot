# 🚀 Dabeeo 맞춤형 신안보/공공 입찰공고 인텔리전스 봇

본 프로젝트는 **나라장터(G2B)**를 매일 자동으로 모니터링하여, 다비오(Dabeeo)의 비즈니스 도메인에 최적화된 핵심 사업 기회만을 규칙 기반 스코어링 엔진으로 선별해 담당자에게 이메일로 브리핑하는 자동화 파이프라인입니다. 
(국방전자조달(D2B) 연동은 코드에 훅만 준비되어 있고 아직 실제 수집기는 구현되지 않았습니다 — [D2B 연동 상태](#d2b-연동-상태) 참고)

---

## 📁 파일 구성 및 역할

리포지토리의 각 파일은 명확히 분리된 역할을 가집니다. 실제로 GitHub Actions가 실행하는 진입점은 `dabeeo_bid_master.py`가 아니라 **`g2b_bot_email.py`**입니다.

| 파일 | 역할 |
| --- | --- |
| **`dabeeo_bid_master.py`** | **핵심 로직 라이브러리.** 직접 실행되지 않고 `import`되어 사용됩니다. 전역 설정(`RECEIVERS`, `KEYWORDS`), 규칙 기반 스코어링 엔진(`calculate_score`), G2B API 수집(`fetch_g2b_bids`), SQLite 상태 저장(`init_db`, `save_bids_to_db`, `filter_new_bids`) 등 시스템의 두뇌 역할을 합니다. |
| **`g2b_bot_email.py`** | **실행 진입점(entry point).** GitHub Actions가 매일 실제로 실행(`python g2b_bot_email.py`)하는 파일입니다. 마스터 모듈에서 데이터를 가져와 HTML 이메일을 조립하고 SMTP로 발송한 뒤, 신규 공고만 DB에 저장합니다. |
| **`test_scoring.py`** | **스코어링 회귀 테스트.** 라벨링된 실제/가상 공고 제목 목록(TIER-A/B/C, 범위 밖, 동형이의어 함정 등)으로 `calculate_score()`의 판정이 흔들리지 않는지 검증합니다. CI에서 본 실행 전에 자체 테스트(self-test)로 먼저 돌아갑니다. |
| **`requirements.txt`** | 의존 패키지: `requests`, `urllib3` (G2B API 호출 및 재시도 로직용). |
| **`.github/workflows/daily_brief.yml`** | GitHub Actions 크론 설정. 스케줄, 시크릿 주입, DB 캐시 유지, 실행 순서(테스트 → 본 실행)를 정의합니다. |

> ⚠️ **주의:** `dabeeo_bid_master.py`는 라이브러리이므로 `python dabeeo_bid_master.py`로 직접 실행하면 안 됩니다 (그렇게 실행할 경우를 위한 진입점이 아닙니다). 항상 `python g2b_bot_email.py`로 실행하세요.

---

## 🧠 스코어링 엔진 (`calculate_score`)

공고 제목(및 발주기관명)을 아래 레이어를 순서대로 통과시키며 점수·등급·판정 근거를 산출합니다.

1. **L0 정규화** — 띄어쓰기/전각문자 등을 표준화.
2. **L1 범위 판정** — 공모전, 기업 모집, RFI/LTA/RFQ 등 입찰공고가 아닌 별도 경로는 즉시 `제외`.
3. **L2 하드 제외** — 제조, 공사, 청소, 급식, 서버·하드웨어 납품 등 다비오 무관 공고를 정규식으로 즉시 차단 (기관명 오탐 방지용 lookaround 포함).
4. **L2b 소프트 제외 + 구제** — '유지보수/구매/설치' 등은 원칙적으로 제외하되, 도메인 핵심 키워드가 2개 이상 겹치면 감점(-25)으로 구제.
5. **L2c 감점** — 감리(-35), 타당성조사(-10) 등 스코프 밖이지만 하드킬은 과한 항목.
6. **L3 동형이의어 가드** — '위성TV', '학습지도' 등 오탐 방지.
7. **L4 가산** — 브랜드(다비오/어스아이 등, +40) > 코어(위성영상 등, +35) > 미드 > 인접 > 약가중 순으로 가산.
8. **L5 동시출현 보너스** — 도메인 코어 키워드 × AI/분석 등 기술 키워드가 함께 나오면 +20.
9. **L6 컨텍스트** — 발주기관 화이트리스트(항우연·국토지리정보원·방위사업청 등, +15), 추정가격 하한 미달 감점, 참가자격(GS인증·공간정보사업자 등록 등) 미보유 항목은 감점 없이 "사람 검토 필요" 플래그만 세움.
10. **L7 허들 + 등급 매핑**

### 등급 기준 (`SCORE_HIGH_CUT=50`, `SCORE_MID_CUT=20`)

| 등급 | 조건 |
| --- | --- |
| 🎯 **상 (핵심 타겟)** | 점수 50점 이상 **AND** 허들 키워드(위성·항공사진·드론·공간정보·다비오 시그니처 기술 등) 통과 **AND** 도메인 강신호(동시출현 보너스 또는 도메인 코어 2개 이상) |
| 🔍 **중 (검토 권장)** | 20~50점, 또는 50점 이상이나 위 허들·강신호 조건 미충족 |
| ❌ **제외** | 20점 미만, 하드 제외 키워드 검출, 범위 밖, 소프트 제외 구제 실패 |

---

## 🔌 G2B 데이터 수집

`fetch_g2b_bids()`는 나라장터 입찰공고정보서비스(용역, `getBidPblancListInfoServcPPSSrch`)를 **시드 키워드별로 개별 질의**하여 API 단에서 1차 필터링합니다 (기본 `days=3`, 즉 최근 3일 이내 등록·미마감 공고).

## D2B 연동 상태

코드에는 `fetch_d2b_bids`를 옵셔널로 불러오는 구조(`try/except ImportError`)가 마련되어 있어, 추후 `dabeeo_bid_master.py`에 `fetch_d2b_bids()` 함수를 추가하기만 하면 자동으로 파이프라인에 합류합니다. **현재 시점에는 이 함수가 구현되어 있지 않아 G2B만 수집됩니다.**

---

## 💡 리포트 활용 가이드 (FAQ)

**Q. 매일 몇 건이나 오나요?**
> 그날 통과된 '상'/'중' 등급 공고 **전체**가 발송되며, 그중 이전에 못 봤던(DB에 없던) 신규 건에는 🆕 배지가 붙습니다. DB에는 신규 건만 저장됩니다.

**Q. 마감된 공고도 오나요?**
> 발송 시점 기준 입찰/참가 등록이 마감되지 않은 '진행 중' 유효 공고만 선별됩니다.

**Q. 단순 제조/공사/물품은 안 보이나요?**
> 네, 하드 제외 키워드(제조·공사·서버·하드웨어 등)와 공고 분류(`ntceKindNm`) 검증을 거쳐 자동 제외됩니다.

**Q. '참가자격 확인 필요' 배지는 뭔가요?**
> GS인증, 공간정보사업자 등록, 측량업 등록 등 카탈로그상 다비오 보유 여부가 확인되지 않은 자격 요건이 언급된 공고입니다. 감점하지 않고 사람이 직접 보유 여부를 확인하도록 플래그만 표시합니다.

---

## 🛠 시스템 커스터마이징 가이드

핵심 설정과 스코어링 규칙은 전부 `dabeeo_bid_master.py`의 **`1. 시스템 통합 글로벌 설정`** / **`2. 다비오 고도화 스코어링`** 영역에 있습니다.

* **수신자(이메일) 변경**
  코드에 하드코딩되어 있지 않고 GitHub Secrets의 `RECEIVER_EMAIL`(콤마로 구분된 문자열)에서 읽습니다.
  → `Settings > Secrets and variables > Actions`에서 `RECEIVER_EMAIL` 값을 수정하세요. (예: `lucas.park@dabeeo.com,new.member@dabeeo.com`)

* **제외할 단어(네거티브 키워드) 추가**
  `NEGATIVE_KEYWORDS`(하드 제외) 또는 `SOFT_EXCLUDE_KEYWORDS`(구제 가능 제외)에 정규식을 추가합니다.

* **가중치 키워드 수정**
  `BRAND_WEIGHT_KEYWORDS`(+40 내외), `HIGH_WEIGHT_KEYWORDS`(코어), `MID_WEIGHT_KEYWORDS`, `ADJACENT_KEYWORDS`, `WEAK_KEYWORDS`에 단어를 추가/조정합니다. API 검색 시드 키워드는 최상단 `KEYWORDS` 리스트입니다.

* **발주기관 화이트리스트 / 참가자격 항목 추가**
  `AGENCY_WHITELIST`, `ELIGIBILITY_PATTERNS`에 추가합니다.

수정 후에는 반드시 `python test_scoring.py`로 회귀 테스트를 돌려 기존 판정이 깨지지 않았는지 확인하세요.

---

## ⚙️ 실행 및 운영 방법

### 1. 자동 실행 (Cron Schedule)
GitHub Actions가 **평일(월~금) KST 오전 08:30**에 자동 실행됩니다 (`.github/workflows/daily_brief.yml`). 실행 순서는 `test_scoring.py`(자체 테스트) → `g2b_bot_email.py`(본 실행) 이며, 중복 발송 방지를 위한 SQLite 상태 파일은 Actions 캐시로 런 간 유지됩니다.

### 2. 수동 실행 (Manual Trigger)
1. 리포지토리 상단 **Actions** 탭 이동
2. **Daily Satellite Bid Briefing** 워크플로우 선택
3. **Run workflow** 클릭 (약 1~2분 소요 후 메일 발송)

### 3. 환경 변수 (Secrets) 셋팅
`Settings > Secrets and variables > Actions`에 아래 값이 등록되어 있어야 합니다.

| Secret | 용도 |
| --- | --- |
| `G2B_API_KEY` | 나라장터 입찰공고정보서비스 API 인증키 |
| `SMTP_USER` | 발송용 GMAIL 주소 |
| `SMTP_PASSWORD` | GMAIL 앱 비밀번호(16자리) |
| `RECEIVER_EMAIL` | 수신자 이메일(콤마 구분, 복수 가능) |

### 4. 로컬 실행
```bash
pip install -r requirements.txt
export G2B_API_KEY=...
export SMTP_USER=... SMTP_PASSWORD=... RECEIVER_EMAIL=...
python test_scoring.py     # 회귀 테스트
python g2b_bot_email.py    # 본 실행
```

---

**Maintainer:** Dabeeo Inc. (Lucas Park, Joohyeon Kim)
**Last Updated:** 2026. 08.
