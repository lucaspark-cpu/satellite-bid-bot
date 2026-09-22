# -*- coding: utf-8 -*-
"""
video_training_data_monitor.py — D2B(국방전자조달) "(26G044-H)영상 기반
학습데이터 구축 자동화" 관련 입찰공고 감시 봇

설계 개요
---------
- shinangbo_monitor.py와 마찬가지로 dabeeo_bid_master.py의 D2B 연동 유틸을
  그대로 재사용한다 (엔드포인트, 인증키 디코딩, XML 파싱 로직 중복 방지).
- G2B 미사용, D2B 국내경쟁입찰공고(getDmstcCmpetBidPblancList)만 조회.
- 판정 로직: 아래 둘 중 하나만 맞아도 매칭 (OR).
    1) 제목에 "영상" + "학습" + "데이터" 세 키워드가 모두 포함 (AND)
    2) 제목에 과제코드 "26G044-H"가 포함 (재공고 등으로 제목 문구가
       바뀌어도 사업코드는 남아있는 경우가 많아 보완용으로 추가)
  둘 다 전각/공백 정규화 후 단순 포함 매칭이며, 동의어 치환은 쓰지 않는다
  (사유는 아래 normalize 관련 주석 참고). 코드 매칭은 대소문자/괄호
  유무 차이도 허용한다.
- 도미니카 봇과 마찬가지로 상태파일(STATE_FILE)로 신규 여부를 관리한다:
  이전에 알림을 보낸 적 없는 공고 id는 "신규"로 상단에 강조 표시하고,
  이미 안내한 적 있는 공고는 "기존" 목록에 그대로 유지해서 매번 전체
  현황을 한 눈에 볼 수 있게 한다. (도미니카 봇과 달리 이메일을 두 개로
  나누지 않고, 하나의 이메일 안에서 신규/기존 섹션만 구분한다.)
- 수신자는 이번 실행에서 매칭된 공고가 있는지에 따라 분기한다:
    - 매칭 공고 0건 → lucas.park@dabeeo.com 1명에게만 발송
    - 매칭 공고 1건 이상(신규/기존 무관) → 도미니카 봇과 동일한 3명
      (lucas.park@dabeeo.com, team_biz-plan@dabeeo.com, injun.park@dabeeo.com)
      에게 발송
- 상태파일명은 도미니카(sent_bids.json), 신안보(상태파일 없음)와 겹치지
  않도록 seen_video_training_data.json으로 분리한다.

외부 네트워크 호출은 fetch_matching_bids()에서만 발생한다.
"""

from __future__ import annotations

import json
import os
import smtplib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any, Dict, List, Tuple

import unicodedata

# dabeeo_bid_master.py에 이미 있는 D2B 연동 유틸을 그대로 재사용한다.
# 주의: normalize()는 여기서 일부러 가져오지 않는다. dabeeo_bid_master.py의
# normalize()는 자체 스코어링 엔진 전용 동의어 정규화(_HANGUL_CANON)를 포함하고
# 있어서, 예를 들어 "항공영상"→"항공사진", "영상레이더"→"합성개구레이더"처럼
# 원문에 있던 "영상"이라는 글자 자체를 지워버리는 경우가 있다. 신안보 봇은
# 키워드가 1개("신안보")라 우연히 이 테이블과 겹치지 않았지만, 여기서는
# "영상"/"학습"/"데이터" 3개를 AND로 보는 것이므로 동의어 치환 없는 단순
# 정규화(도미니카 봇과 동일한 방식)를 직접 쓴다.
from dabeeo_bid_master import (
    D2B_BASE,
    D2B_DMSTC_LIST_OP,
    D2B_NUM_OF_ROWS,
    KST,
    _d2b_api_key,
    _d2b_text,
    _session,
    _to_int,
    escape,
)


def _normalize_compact(text: str) -> str:
    """전각문자 표준화 + 공백 제거만 수행 (동의어 치환 없음)."""
    text = unicodedata.normalize("NFKC", text or "")
    return "".join(text.split())


def _code_compact(text: str) -> str:
    """과제코드 매칭용: 전각 표준화 + 대문자 통일 + 괄호류/공백 제거.
    하이픈(-)은 코드의 일부이므로 남겨둔다 (다른 코드와 혼동 방지)."""
    text = unicodedata.normalize("NFKC", text or "").upper()
    for ch in "()[]{}<>「」『』【】〔〕（）《》〈〉":
        text = text.replace(ch, "")
    return "".join(text.split())


# 제목에 아래 키워드가 "모두" 포함되면 매칭 (AND 조건)
KEYWORDS = ["영상", "학습", "데이터"]

# 위 키워드 조합 대신, 제목에 이 과제코드가 포함되어 있어도 매칭 (OR 조건)
CODE_KEYWORD = "26G044-H"

LOOKBACK_DAYS = 30
MAX_PAGES = 10
HTTP_TIMEOUT = (5, 20)  # (connect, read)

# 매 실행마다 항상 받는 사람 (매칭 결과가 없을 때도 이 사람에게는 발송)
ALWAYS_RECIPIENT = "lucas.park@dabeeo.com"

# 매칭된 공고가 1건이라도 있을 때 발송하는 확장 수신자 목록 (도미니카 봇과 동일)
EXPANDED_RECIPIENTS = [
    "lucas.park@dabeeo.com",
    "team_biz-plan@dabeeo.com",
    "injun.park@dabeeo.com",
]

STATE_FILE = Path(__file__).parent / "seen_video_training_data.json"

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

def _date_window(days: int) -> Tuple[str, str]:
    """D2B는 시간 없이 YYYYMMDD 8자리 날짜만 받는다."""
    now = datetime.now(KST)
    bgn = (now - timedelta(days=days)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    return bgn, end


def _is_match(title: str) -> bool:
    compact = _normalize_compact(title)
    keyword_hit = all(_normalize_compact(kw) in compact for kw in KEYWORDS)
    code_hit = CODE_KEYWORD.upper() in _code_compact(title)
    return keyword_hit or code_hit


def fetch_matching_bids() -> List[Dict[str, Any]]:
    """D2B 국내경쟁입찰공고 중 KEYWORDS 전부 포함 또는 CODE_KEYWORD 포함인 건만 골라 반환."""
    key = _d2b_api_key()
    if not key:
        print("[WARN] D2B_API_KEY 환경변수가 없습니다.")
        return []

    bgn, end = _date_window(LOOKBACK_DAYS)
    url = f"{D2B_BASE}/{D2B_DMSTC_LIST_OP}"
    sess = _session()

    seen_in_run: set = set()
    results: List[Dict[str, Any]] = []

    for page in range(1, MAX_PAGES + 1):
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
            print(f"[D2B API ERROR] p{page}: XML 파싱 실패 → {r.text[:200]}")
            break

        header = root.find("header")
        code = _d2b_text(header, "resultCode") or "00"
        if code not in ("00", "0"):
            print(f"[D2B API WARN] resultCode={code} msg={_d2b_text(header, 'resultMsg')}")
            print(f"[D2B API RAW] {r.text[:500]}")
            break

        body = root.find("body")
        items = body.findall("items/item") if body is not None else []
        if not items:
            break

        for it in items:
            pblanc_no = _d2b_text(it, "pblancNo")
            pblanc_odr = _d2b_text(it, "pblancOdr")
            uid = f"{pblanc_no}-{pblanc_odr}" if pblanc_odr else pblanc_no
            if not uid or uid in seen_in_run:
                continue
            seen_in_run.add(uid)

            title = _d2b_text(it, "bidNm")
            if not _is_match(title):
                continue

            agency = _d2b_text(it, "ornt") or "미지정 기관"
            deadline = (
                _d2b_text(it, "biddocPresentnClosDt")
                or _d2b_text(it, "opengDt")
                or "진행중"
            )

            g2b_no = _d2b_text(it, "g2bPblancNo")
            g2b_odr = _d2b_text(it, "g2bPblancOdr")
            dcs_no = _d2b_text(it, "dcsNo")
            search_no = (
                (f"{g2b_no}-{g2b_odr}" if g2b_odr else g2b_no) if g2b_no
                else (dcs_no or uid)
            )

            results.append({
                "uid": uid,
                "bid_no": search_no,
                "bid_name": title,
                "order_agency": agency,
                "bid_date": deadline,
            })

        total = _to_int(_d2b_text(body, "totalCount"))
        if page * D2B_NUM_OF_ROWS >= total:
            break

    results.sort(key=lambda b: b["bid_name"])
    print(f"--- D2B 조회 {len(seen_in_run)}건 / 키워드 매칭 {len(results)}건 ---")
    return results


# ---------------------------------------------------------------------------
# 상태(신규 판단 이력) 관리
# ---------------------------------------------------------------------------

def load_seen_ids() -> set:
    if not STATE_FILE.exists():
        return set()
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen_ids(ids: set) -> None:
    STATE_FILE.write_text(
        json.dumps(sorted(ids), ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 이메일 본문 구성
# ---------------------------------------------------------------------------

def _bid_card_html(b: Dict[str, Any], *, highlight: bool) -> str:
    border_color = "#e53e3e" if highlight else "#a0aec0"
    return f"""
    <div style="background-color:#f7fafc;border-left:4px solid {border_color};
                border-radius:4px;padding:16px;margin-bottom:16px;">
      <div style="font-size:15px;font-weight:bold;color:#1a202c;margin-bottom:10px;">
        {escape(b['bid_name'])}
      </div>
      <div style="font-size:13px;color:#4a5568;margin-bottom:4px;">
        ♦ <strong>발주기관:</strong> {escape(b['order_agency'])}
      </div>
      <div style="font-size:13px;color:#4a5568;margin-bottom:4px;">
        ♦ <strong>공고번호:</strong>
        <span style="background-color:#edf2f7;padding:2px 6px;border-radius:3px;
                     font-family:monospace;">{escape(b['bid_no'])}</span>
      </div>
      <div style="font-size:13px;color:#4a5568;">
        ♦ <strong>마감일시:</strong>
        <span style="color:#e53e3e;font-weight:bold;">{escape(b['bid_date'])}</span>
      </div>
      <div style="margin-top:14px;">
        <a href="https://www.d2b.go.kr" target="_blank"
           style="background-color:#2d3748;color:#ffffff;padding:8px 14px;
                  font-size:12px;font-weight:bold;text-decoration:none;
                  border-radius:4px;display:inline-block;">
          D2B 시스템 이동 (공고번호 복사 필수)
        </a>
      </div>
    </div>
    """


def build_email_html(new_items: List[Dict[str, Any]], old_items: List[Dict[str, Any]]) -> str:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    keyword_label = " + ".join(KEYWORDS)

    new_section = (
        "".join(_bid_card_html(b, highlight=True) for b in new_items)
        if new_items
        else '<p style="font-size:13px;color:#718096;">신규 공고가 없습니다.</p>'
    )
    old_section = (
        "".join(_bid_card_html(b, highlight=False) for b in old_items)
        if old_items
        else '<p style="font-size:13px;color:#718096;">기존에 안내된 공고가 없습니다.</p>'
    )

    return f"""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"></head>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
                 'Helvetica Neue',Arial,sans-serif;color:#333333;line-height:1.6;
                 margin:0;padding:20px;background-color:#ffffff;">
      <div style="max-width:900px;margin:0 auto;">
        <h2 style="font-size:20px;font-weight:bold;color:#1a202c;margin-bottom:8px;">
          D2B &quot;{keyword_label}&quot; 입찰공고 리포트 ({today})
        </h2>
        <p style="font-size:13px;color:#718096;margin-top:0;margin-bottom:24px;">
          국방전자조달(D2B) 국내경쟁입찰공고 중 제목에 &quot;{keyword_label}&quot;가
          모두 포함되었거나 과제코드 &quot;{CODE_KEYWORD}&quot;가 포함된 건,
          최근 {LOOKBACK_DAYS}일 기준 (신규 {len(new_items)}건 / 기존 {len(old_items)}건)
        </p>

        <h3 style="font-size:15px;font-weight:bold;color:#c53030;border-bottom:2px solid #e53e3e;
                   padding-bottom:6px;margin:20px 0 12px 0;">
          🆕 신규 ({len(new_items)}건)
        </h3>
        {new_section}

        <h3 style="font-size:15px;font-weight:bold;color:#718096;border-bottom:2px solid #cbd5e0;
                   padding-bottom:6px;margin:28px 0 12px 0;">
          기존 (이미 안내됨, {len(old_items)}건)
        </h3>
        {old_section}
      </div>
    </body></html>
    """


def send_email(
    recipients: List[str],
    new_items: List[Dict[str, Any]],
    old_items: List[Dict[str, Any]],
) -> bool:
    """이메일 발송 성공 여부를 bool로 반환한다 (상태파일 갱신 여부 판단에 사용)."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("[ERROR] SMTP_USER / SMTP_PASSWORD 환경변수가 없습니다.")
        return False
    if not recipients:
        print("[ERROR] 수신자 목록이 비어 있습니다.")
        return False

    total = len(new_items) + len(old_items)
    html_content = build_email_html(new_items, old_items)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[D2B 영상학습데이터 리포트] 신규 {len(new_items)}건 / 전체 {total}건"
    msg["From"] = formataddr(("Dabeeo Bid Bot", SMTP_USER))
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"[SUCCESS] 이메일 발송 완료 → {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"[ERROR] 이메일 발송 실패: {e}")
        return False


def main() -> None:
    bids = fetch_matching_bids()
    seen_ids = load_seen_ids()

    new_items = [b for b in bids if b["uid"] not in seen_ids]
    old_items = [b for b in bids if b["uid"] in seen_ids]

    # 매칭된 공고가 1건이라도 있으면(신규/기존 무관) 확장 수신자, 없으면 본인만.
    recipients = EXPANDED_RECIPIENTS if bids else [ALWAYS_RECIPIENT]

    sent_ok = send_email(recipients, new_items, old_items)

    # 발송에 성공했을 때만 "이미 본 것"으로 표시한다. 실패하면 상태를 그대로 두어
    # 다음 실행에서 같은 건이 다시 "신규"로 재시도되게 한다 (도미니카 봇과 동일한 원칙).
    if sent_ok:
        seen_ids.update(b["uid"] for b in bids if b["uid"])
        save_seen_ids(seen_ids)
    else:
        print("[WARN] 발송 실패로 상태파일을 갱신하지 않음 (다음 실행에서 재시도)")


if __name__ == "__main__":
    main()
