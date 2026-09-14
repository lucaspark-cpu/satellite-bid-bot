"""
도미니카(공) ICT기반 국립공원 기후변화 모니터링 역량 고도화 사업
관련 나라장터 입찰공고를 감시하고, 신규/변경 공고 발견 시 이메일로 알린다.

실행 주기: GitHub Actions에서 하루 3회(09:00 / 13:00 / 17:00 KST) 호출.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 설정 (코드 내에서 직접 수정)
# ---------------------------------------------------------------------------

# 수신자 이메일 - 여기서 직접 추가/삭제
RECIPIENTS: list[str] = [
    "team_biz-plan@dabeeo.com",
    "injun.park@dabeeo.com"
]

# 판정 키워드: "도미니카"는 필수, 아래 중 1개 이상이 추가로 있어야 알림
BASE_KEYWORD = "도미니카"
EXTRA_KEYWORDS: list[str] = [
    "ICT",
    "국립공원",
    "기후변화",
    "모니터링",
    "역량",
    "고도화",
    "시스템",
    "구축",
    "용역",
    "공원",
]

# 조회 대상 기간 (일). 공고가 늦게 게시되는 경우를 대비해 여유 있게 잡음.
LOOKBACK_DAYS = 14

STATE_FILE = Path(__file__).parent / "sent_bids.json"

# 나라장터 입찰공고정보서비스(공공데이터포털) - 용역 공고 조회
# NOTE: 공공데이터포털 API는 개편이 잦으므로, 기존 satellite-bid-bot에서
# 실제로 쓰고 있는 엔드포인트/파라미터명과 다르면 그쪽 값으로 맞춰서 교체할 것.
API_BASE_URL = "http://apis.data.go.kr/1230000/BidPublicInfoService04/getBidPublicInfoServc"
SERVICE_KEY = os.environ.get("G2B_SERVICE_KEY", "")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


# ---------------------------------------------------------------------------
# 텍스트 정규화 / 매칭
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """전각문자 표준화 + 공백 제거 (compact 버전)."""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text)


def is_match(title: str) -> bool:
    """제목에 BASE_KEYWORD + EXTRA_KEYWORDS 중 1개 이상이 포함되는지 확인."""
    compact = normalize(title)
    if BASE_KEYWORD not in compact:
        return False
    return any(normalize(kw) in compact for kw in EXTRA_KEYWORDS)


# ---------------------------------------------------------------------------
# API 조회
# ---------------------------------------------------------------------------

def fetch_bids() -> list[dict]:
    """최근 LOOKBACK_DAYS 기간의 용역 입찰공고를 조회한다."""
    now = datetime.now(timezone(timedelta(hours=9)))
    begin = now - timedelta(days=LOOKBACK_DAYS)

    params = {
        "serviceKey": SERVICE_KEY,
        "type": "json",
        "inqryDiv": "1",  # 1: 공고게시일시 기준
        "inqryBgnDt": begin.strftime("%Y%m%d0000"),
        "inqryEndDt": now.strftime("%Y%m%d2359"),
        "numOfRows": "500",
        "pageNo": "1",
    }

    resp = requests.get(API_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    header = data.get("response", {}).get("header", {})
    if header.get("resultCode") not in ("00", 0, "0"):
        raise RuntimeError(f"G2B API 오류: {header}")

    body = data.get("response", {}).get("body", {})
    items = body.get("items", []) or []
    # 단일 결과일 때 dict로 오는 경우 대비
    if isinstance(items, dict):
        items = [items]
    return items


# ---------------------------------------------------------------------------
# 상태(중복 방지) 관리
# ---------------------------------------------------------------------------

def load_sent_ids() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def save_sent_ids(ids: set[str]) -> None:
    STATE_FILE.write_text(
        json.dumps(sorted(ids), ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 이메일 발송
# ---------------------------------------------------------------------------

def build_email_body(matches: list[dict]) -> str:
    lines = ["도미니카 관련 신규/변경 입찰공고가 발견되었습니다.\n"]
    for item in matches:
        title = item.get("bidNtceNm", "(제목 없음)")
        notice_no = item.get("bidNtceNo", "(공고번호 없음)")
        agency = item.get("ntceInsttNm", "(발주기관 미상)")
        notice_dt = item.get("bidNtceDt", "")
        lines.append(
            f"- 공고명: {title}\n"
            f"  발주기관: {agency}\n"
            f"  공고번호: {notice_no}  (나라장터에서 이 번호로 직접 검색)\n"
            f"  공고일시: {notice_dt}\n"
        )
    return "\n".join(lines)


def send_email(matches: list[dict]) -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD 환경변수가 설정되지 않았습니다.")
    if not RECIPIENTS:
        raise RuntimeError("RECIPIENTS 목록이 비어 있습니다.")

    body = build_email_body(matches)
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = f"[입찰알림] 도미니카 관련 공고 {len(matches)}건 발견"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ", ".join(RECIPIENTS)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENTS, msg.as_string())


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        bids = fetch_bids()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 공고 조회 실패: {exc}", file=sys.stderr)
        return 1

    sent_ids = load_sent_ids()
    matches = [
        b for b in bids
        if is_match(b.get("bidNtceNm", "")) and b.get("bidNtceNo") not in sent_ids
    ]

    if not matches:
        print("신규 매칭 공고 없음.")
        return 0

    try:
        send_email(matches)
    except Exception as exc:  # noqa: BLE001
        # 발송 실패 시 sent_ids를 절대 갱신하지 않는다 (다음 실행에서 재시도되도록).
        print(f"[ERROR] 이메일 발송 실패: {exc}", file=sys.stderr)
        return 1

    # 발송이 성공했을 때만 상태 저장 (중복 방지).
    sent_ids.update(b["bidNtceNo"] for b in matches if b.get("bidNtceNo"))
    save_sent_ids(sent_ids)
    print(f"이메일 발송 완료: {len(matches)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
