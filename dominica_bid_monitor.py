"""
"도미니카" 관련 나라장터 입찰공고를 감시해 매 실행마다 이메일로 상태를 보고한다.

- 최근 7일 공고는 있든 없든 매번 이메일 발송 (상단에 정리)
- 최근 30일 이력은 별도 리스트로 함께 정리 (8~30일 전, 최근 7일과 중복 제외)
- 취소/변경/재공고 등 공고 종류에 상관없이 제목에 "도미니카"가 들어간 건 모두 포함

실행 주기: GitHub Actions에서 하루 3회(09:00 / 13:00 / 17:00 KST) 호출.
"""

from __future__ import annotations

import html
import os
import smtplib
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import requests

# ---------------------------------------------------------------------------
# 설정 (코드 내에서 직접 수정)
# ---------------------------------------------------------------------------

# 수신자 이메일 - 여기서 직접 추가/삭제
RECIPIENTS: list[str] = [
    "team_biz-plan@dabeeo.com",
    "injun.park@dabeeo.com"
]

# 판정 키워드: 제목에 이 단어만 포함되면 매칭 (취소/변경/재공고 등 종류 무관)
BASE_KEYWORD = "도미니카"

RECENT_DAYS = 7    # 이 기간은 매번 상단에 정리
HISTORY_DAYS = 30  # 이 기간 전체를 조회하고, RECENT_DAYS 이전 것만 이력 리스트로 별도 정리

KST = timezone(timedelta(hours=9))

# 나라장터 검색조건에 의한 입찰공고 서비스(공공데이터포털) - 용역
# NOTE: 기존 satellite-bid-bot(dabeeo_bid_master.py)에서 실제로 검증된 값 그대로 사용.
G2B_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
G2B_SERVC_OP = "getBidPblancListInfoServcPPSSrch"
API_BASE_URL = f"{G2B_BASE}/{G2B_SERVC_OP}"
MAX_PAGES = 5
NUM_OF_ROWS = 100

# 인코딩 키를 넣어도 안전하도록 1회 디코드 (satellite-bid-bot과 동일 방식)
SERVICE_KEY = urllib.parse.unquote(os.environ.get("G2B_API_KEY", ""))

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


# ---------------------------------------------------------------------------
# 텍스트 정규화 / 매칭 / 날짜 파싱
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """전각문자 표준화 + 공백 제거 (compact 버전)."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(text.split())


def is_match(title: str) -> bool:
    """제목에 BASE_KEYWORD가 포함되는지 확인 (취소/변경/재공고 등 종류 무관)."""
    return BASE_KEYWORD in normalize(title)


def parse_notice_dt(item: dict) -> datetime | None:
    """bidNtceDt 필드("YYYY-MM-DD HH:MM:SS")를 KST datetime으로 파싱."""
    raw = (item.get("bidNtceDt") or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# API 조회
# ---------------------------------------------------------------------------

def _get_with_retry(params: dict) -> dict:
    """apis.data.go.kr는 GitHub Actions 러너 IP를 간헐적으로 막는 경우가 있어 재시도한다."""
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(API_BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[WARN] 공고 조회 {attempt}차 시도 실패: {exc}", file=sys.stderr)
            if attempt < 3:
                time.sleep(10 * attempt)
    raise RuntimeError(f"공고 조회 3회 재시도 모두 실패: {last_exc}")


def fetch_bids_90d() -> list[dict]:
    """최근 HISTORY_DAYS 기간의 "도미니카" 관련 용역 입찰공고를 전부 조회한다 (data.go.kr 조회기간 제한상 30일 이내 유지).

    취소/변경/재공고를 걸러내지 않도록 bidClseExcpYn(마감 제외) 파라미터는 쓰지 않는다.
    """
    now = datetime.now(KST)
    begin = now - timedelta(days=HISTORY_DAYS)

    seen: set[str] = set()
    results: list[dict] = []

    for page in range(1, MAX_PAGES + 1):
        params = {
            "serviceKey": SERVICE_KEY,
            "type": "json",
            "numOfRows": str(NUM_OF_ROWS),
            "pageNo": str(page),
            "inqryDiv": "1",  # 1: 공고게시일시 기준
            "inqryBgnDt": begin.strftime("%Y%m%d0000"),
            "inqryEndDt": now.strftime("%Y%m%d%H%M"),
            "bidNtceNm": BASE_KEYWORD,  # 서버단 1차 필터
        }
        data = _get_with_retry(params)

        # 정상 스키마: {"response": {"header": {...}, "body": {...}}}
        # 오류(인증/트래픽 등) 시 다른 스키마로 오는 경우가 있어, 그 경우 전체 응답을 그대로 노출한다.
        if "response" not in data:
            alt = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {})
            if alt:
                raise RuntimeError(
                    f"G2B API 오류: {alt.get('errMsg')} / {alt.get('returnAuthMsg')} "
                    f"(returnReasonCode={alt.get('returnReasonCode')})"
                )
            raise RuntimeError(f"G2B API 오류: 예상치 못한 응답 형식 → {data}")

        header = data.get("response", {}).get("header", {})
        if header.get("resultCode") not in ("00", 0, "0"):
            raise RuntimeError(f"G2B API 오류: {header}")

        body = data.get("response", {}).get("body", {})
        items = body.get("items", []) or []
        if isinstance(items, dict):
            items = [items]
        if not items:
            break

        for it in items:
            bid_no = str(it.get("bidNtceNo") or "").strip()
            ord_no = str(it.get("bidNtceOrd") or "").strip()
            uid = f"{bid_no}-{ord_no}" if ord_no else bid_no
            if not uid or uid in seen:
                continue
            seen.add(uid)
            if is_match(it.get("bidNtceNm", "")):
                results.append(it)

        if len(items) < NUM_OF_ROWS:
            break  # 마지막 페이지

    return results


# ---------------------------------------------------------------------------
# 이메일 본문 구성
# ---------------------------------------------------------------------------

def _escape(text) -> str:
    return html.escape(str(text or ""))


def _bid_card_html(item: dict) -> str:
    title = _escape(item.get("bidNtceNm", "(제목 없음)"))
    agency = _escape(item.get("ntceInsttNm", "(발주기관 미상)"))
    notice_no = _escape(item.get("bidNtceNo", ""))
    notice_dt = _escape(item.get("bidNtceDt", ""))
    region = _escape(item.get("prtcptLmtRgnNm") or "전국/제한없음")

    return f"""
    <div style="background-color:#f7fafc;border-left:4px solid #3182ce;border-radius:4px;
                padding:14px 16px;margin-bottom:12px;">
      <div style="font-size:14px;font-weight:bold;color:#1a202c;margin-bottom:8px;">
        {title}
      </div>
      <div style="font-size:12px;color:#4a5568;margin-bottom:2px;">
        ♦ 발주기관: {agency}
      </div>
      <div style="font-size:12px;color:#4a5568;margin-bottom:2px;">
        ♦ 지역제한: <span style="color:#2f855a;font-weight:bold;">{region}</span>
        &nbsp;|&nbsp; 공고번호:
        <span style="background-color:#edf2f7;padding:1px 5px;border-radius:3px;
                     font-family:monospace;">{notice_no}</span>
      </div>
      <div style="font-size:12px;color:#4a5568;">
        ♦ 공고일시: {notice_dt}
      </div>
      <div style="margin-top:10px;">
        <a href="https://www.g2b.go.kr" target="_blank"
           style="background-color:#3182ce;color:#ffffff;padding:6px 12px;font-size:11px;
                  font-weight:bold;text-decoration:none;border-radius:4px;display:inline-block;">
          나라장터에서 공고번호로 검색
        </a>
      </div>
    </div>
    """


def build_email_html(recent: list[dict], history: list[dict]) -> str:
    recent_section = (
        "".join(_bid_card_html(b) for b in recent)
        if recent
        else '<p style="font-size:13px;color:#718096;">최근 7일간 "도미니카" 관련 공고가 없습니다.</p>'
    )
    history_section = (
        "".join(_bid_card_html(b) for b in history)
        if history
        else '<p style="font-size:13px;color:#718096;">8~30일 전 이력이 없습니다.</p>'
    )

    return f"""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"></head>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
                 color:#333333;line-height:1.6;margin:0;padding:20px;background-color:#ffffff;">
      <div style="max-width:700px;margin:0 auto;">
        <h2 style="font-size:20px;font-weight:bold;color:#1a202c;margin-bottom:16px;">
          🔎 "도미니카" 입찰공고 모니터링
        </h2>

        <h3 style="font-size:15px;font-weight:bold;color:#2b6cb0;border-bottom:2px solid #3182ce;
                   padding-bottom:6px;margin:20px 0 12px 0;">
          최근 7일 ({len(recent)}건)
        </h3>
        {recent_section}

        <h3 style="font-size:15px;font-weight:bold;color:#718096;border-bottom:2px solid #cbd5e0;
                   padding-bottom:6px;margin:28px 0 12px 0;">
          이력 (8~30일 전, {len(history)}건)
        </h3>
        {history_section}
      </div>
    </body></html>
    """


def send_html_email(subject: str, html_body: str) -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD 환경변수가 설정되지 않았습니다.")
    if not RECIPIENTS:
        raise RuntimeError("RECIPIENTS 목록이 비어 있습니다.")

    msg = MIMEText(html_body, "html", _charset="utf-8")
    msg["Subject"] = subject
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
        all_bids = fetch_bids_90d()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 공고 조회 실패: {exc}", file=sys.stderr)
        return 1

    now = datetime.now(KST)
    cutoff = now - timedelta(days=RECENT_DAYS)

    recent: list[dict] = []
    history: list[dict] = []
    for item in all_bids:
        dt = parse_notice_dt(item)
        if dt is not None and dt >= cutoff:
            recent.append(item)
        else:
            history.append(item)

    recent.sort(key=lambda b: b.get("bidNtceDt", ""), reverse=True)
    history.sort(key=lambda b: b.get("bidNtceDt", ""), reverse=True)

    if recent:
        subject = f'[입찰알림] 최근 7일 "도미니카" 공고 {len(recent)}건'
    else:
        subject = '[입찰알림] 최근 7일 "도미니카" 공고 없음'

    html_body = build_email_html(recent, history)

    try:
        send_html_email(subject, html_body)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 이메일 발송 실패: {exc}", file=sys.stderr)
        return 1

    print(f"이메일 발송 완료 (최근 7일 {len(recent)}건 / 이력 {len(history)}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
