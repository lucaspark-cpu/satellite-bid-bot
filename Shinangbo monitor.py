# -*- coding: utf-8 -*-
"""
shinangbo_monitor.py — D2B(국방전자조달) "신안보" 키워드 감시 봇

dabeeo_bid_master.py의 스코어링 엔진(다비오 맞춤형 상/중/하 등급 판정)과는
완전히 별개로 동작하는 경량 버전이다. 점수 계산 없이 공고명에 "신안보"라는
문자열이 포함되는지만 확인한다.

주의(헷갈리지 않도록): 이 저장소의 README는 dabeeo_bid_master.py 기반 전체
파이프라인을 "신안보/공공 입찰공고 인텔리전스 봇"이라는 브랜드명으로 부르고
있다. 그건 프로젝트 애칭일 뿐이고, 이 파일에서 말하는 "신안보"는 그것과
무관하게 D2B 공고 제목에 실제로 등장하는 문자열을 찾는 키워드다.

설계 (도미니카 봇과의 차이)
---------------------------
- G2B 미사용, D2B 국내경쟁입찰공고(getDmstcCmpetBidPblancList)만 조회.
- 수신자는 lucas.park@dabeeo.com 한 명뿐이라 "신규만 받는 사람" 분기가
  없다. 그래서 신규 판단용 상태 파일/DB도 두지 않는다 — 매 실행마다
  최근 LOOKBACK_DAYS일 전체를 그냥 다시 보여준다.
- 상태를 안 쓰기 때문에 dabeeo_bid_master.py가 관리하는 g2b_bids.db와도
  전혀 간섭하지 않는다 (완전히 독립적인 스크립트).

외부 네트워크 호출은 fetch_shinangbo_bids()에서만 발생한다.
"""

from __future__ import annotations

import os
import smtplib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Dict, List, Tuple

# dabeeo_bid_master.py에 이미 있는 D2B 연동 유틸을 그대로 재사용한다.
# (엔드포인트, 인증키 디코딩, XML 파싱, 정규화 로직을 중복 구현하지 않기 위함)
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
    normalize,
)

KEYWORD = "신안보"
LOOKBACK_DAYS = 30
RECEIVER = "lucas.park@dabeeo.com"
MAX_PAGES = 10  # 30일치 조회라 스코어링 봇(D2B_MAX_PAGES=5)보다 여유를 둠
HTTP_TIMEOUT = (5, 20)  # (connect, read)

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")


def _date_window(days: int) -> Tuple[str, str]:
    """D2B는 시간 없이 YYYYMMDD 8자리 날짜만 받는다."""
    now = datetime.now(KST)
    bgn = (now - timedelta(days=days)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    return bgn, end


def fetch_shinangbo_bids() -> List[Dict[str, Any]]:
    """D2B 국내경쟁입찰공고 중 제목에 '신안보'가 포함된 건만 골라 반환."""
    key = _d2b_api_key()
    if not key:
        print("[WARN] D2B_API_KEY 환경변수가 없습니다.")
        return []

    bgn, end = _date_window(LOOKBACK_DAYS)
    url = f"{D2B_BASE}/{D2B_DMSTC_LIST_OP}"
    sess = _session()
    keyword_compact = normalize(KEYWORD).compact

    seen: set = set()
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
            # 원인이 트래픽초과/서비스없음/인증키오류 등 제각각이라 전체를 로그에 남긴다.
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
            if not uid or uid in seen:
                continue
            seen.add(uid)

            title = _d2b_text(it, "bidNm")
            if keyword_compact not in normalize(title).compact:
                continue

            agency = _d2b_text(it, "ornt") or "미지정 기관"
            deadline = (
                _d2b_text(it, "biddocPresentnClosDt")
                or _d2b_text(it, "opengDt")
                or "진행중"
            )

            # D2B 사이트 검색창에 붙여넣을 '공고번호' 후보 (dabeeo_bid_master.py의
            # fetch_d2b_bids와 동일한 우선순위: g2bPblancNo → dcsNo → 내부 uid)
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
            })

        total = _to_int(_d2b_text(body, "totalCount"))
        if page * D2B_NUM_OF_ROWS >= total:
            break

    results.sort(key=lambda b: b["bid_name"])
    print(f"--- D2B 조회 {len(seen)}건 / '{KEYWORD}' 매칭 {len(results)}건 ---")
    return results


def build_email_html(bids: List[Dict[str, Any]]) -> str:
    today = datetime.now(KST).strftime("%Y-%m-%d")

    if not bids:
        body_html = (
            '<p style="font-size:14px;color:#4a5568;">'
            f'최근 {LOOKBACK_DAYS}일 이내 "{KEYWORD}" 포함 D2B 공고가 없습니다.'
            "</p>"
        )
    else:
        cards = []
        for b in bids:
            cards.append(f"""
            <div style="background-color:#f7fafc;border-left:4px solid #ed8936;
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
            """)
        body_html = "".join(cards)

    return f"""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8"></head>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,
                 'Helvetica Neue',Arial,sans-serif;color:#333333;line-height:1.6;
                 margin:0;padding:20px;background-color:#ffffff;">
      <div style="max-width:900px;margin:0 auto;">
        <h2 style="font-size:20px;font-weight:bold;color:#1a202c;margin-bottom:8px;">
          D2B &quot;{KEYWORD}&quot; 입찰공고 리포트 ({today})
        </h2>
        <p style="font-size:13px;color:#718096;margin-top:0;margin-bottom:24px;">
          국방전자조달(D2B) 국내경쟁입찰공고 중 제목에 &quot;{KEYWORD}&quot;가
          포함된 건, 최근 {LOOKBACK_DAYS}일 기준 (총 {len(bids)}건)
        </p>
        {body_html}
      </div>
    </body></html>
    """


def send_email(bids: List[Dict[str, Any]]) -> None:
    if not SMTP_USER or not SMTP_PASSWORD:
        print("[ERROR] SMTP_USER / SMTP_PASSWORD 환경변수가 없습니다.")
        return

    html_content = build_email_html(bids)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[D2B 신안보 리포트] {len(bids)}건"
    msg["From"] = formataddr(("Dabeeo Bid Bot", SMTP_USER))
    msg["To"] = RECEIVER
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [RECEIVER], msg.as_string())
        print(f"[SUCCESS] 이메일 발송 완료 → {RECEIVER}")
    except Exception as e:
        print(f"[ERROR] 이메일 발송 실패: {e}")


def main() -> None:
    bids = fetch_shinangbo_bids()
    send_email(bids)


if __name__ == "__main__":
    main()
