import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

from dabeeo_bid_master import (
    fetch_g2b_bids,
    save_bids_to_db,
    init_db,
    filter_new_bids,
    escape,
    RECEIVERS,
    TIER_HIGH,
    TIER_MID,
)

try:
    from dabeeo_bid_master import fetch_d2b_bids
except ImportError:
    fetch_d2b_bids = None

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "")

# 검색 키워드 표시용 (dabeeo_bid_master.KEYWORDS 시드와 동기화)
SEARCH_KEYWORDS_STR = "위성영상, 초소형위성, 정사영상, 항공사진, 원격탐사, 변화탐지, 객체탐지, 공간정보, 지리정보, 학습데이터, 드론, 판독"

def build_email_html(bids):
    """보내주신 이미지와 100% 동일한 HTML 메일 양식 생성"""
    total_count = len(bids)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; color: #333333; line-height: 1.6; margin: 0; padding: 20px; background-color: #ffffff;">
        <div style="max-width: 900px; margin: 0 auto;">
            
            <!-- 헤더 영역 -->
            <h2 style="font-size: 22px; font-weight: bold; color: #1a202c; margin-bottom: 12px; display: flex; align-items: center;">
                🚀 나라장터 및 국방전자조달 통합 인텔리전스
            </h2>
            <p style="font-size: 14px; color: #4a5568; margin-top: 0; margin-bottom: 8px;">
                다비오 비즈니스 도메인 연관도 스코어링 알고리즘에 따라 총 <strong style="color: #d69e2e;">{total_count}건</strong>의 진행 중인 유효 공고가 분류되었습니다.
            </p>
            <p style="font-size: 13px; color: #718096; margin-top: 0; margin-bottom: 24px;">
                조회 키워드: {SEARCH_KEYWORDS_STR}
            </p>

            <!-- 활용 가이드 & FAQ 박스 -->
            <div style="background-color: #f0f7ff; border: 1px solid #c3e0ff; border-radius: 8px; padding: 18px 20px; margin-bottom: 28px;">
                <h4 style="font-size: 15px; font-weight: bold; color: #1a365d; margin: 0 0 12px 0;">
                    💡 리포트 100% 활용 가이드 및 FAQ
                </h4>
                <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: #2d3748; line-height: 1.8;">
                    <li style="margin-bottom: 6px;">
                        🎯 <strong>'상 (핵심 타겟)' 분류 기준:</strong> 다비오 핵심 사업인 <strong>'위성', '드론', '공간정보'</strong> 중 최소 1개 이상이 공고면에 명시적으로 포함된 경우에만 '상' 등급에 노출되도록 필터링을 강화했습니다.
                    </li>
                    <li style="margin-bottom: 6px;">
                        🛡️ <strong>국방전자조달(D2B) 공고 확인법:</strong> 국방전자조달 시스템 보안 특성상 상세 링크로의 직접 연결이 어렵습니다. 아래 리스트에서 <strong>'공고번호'를 복사</strong>하신 후 <a href="https://www.d2b.go.kr" target="_blank" style="color: #e53e3e; font-weight: bold; text-decoration: underline;">D2B 홈페이지</a> 검색창에 <strong>붙여넣기</strong> 하시면 상세 내용을 바로 확인하실 수 있습니다.
                    </li>
                    <li style="margin-bottom: 6px;">
                        🔍 <strong>단순 제조/공사/물품은 안 보이나요?:</strong> 네, '제조, 공사, 서버, 하드웨어' 등 30여 개의 강력한 네거티브 필터링 알고리즘을 거쳐 다비오와 무관한 공고는 <strong>전면 자동 제외</strong> 처리됩니다.
                    </li>
                    <li>
                        ⏰ <strong>마감된 공고도 오나요?:</strong> 본 메일은 발송 시점 기준으로 <strong>입찰/참가 등록이 마감되지 않은 '진행 중'인 유효 공고만</strong>을 선별하여 전달합니다.
                    </li>
                </ul>
            </div>

            <!-- 공고 카드 목록 -->
            <div>
    """

    # [NEW] '상 → 중' 등급 순으로 섹션을 나눠 렌더링한다.
    ordered = sorted(
        bids,
        key=lambda b: (0 if b.get('tier') == TIER_HIGH else 1, -int(b.get('score', 0) or 0)),
    )
    current_tier = None
    for bid in ordered:
        tier = bid.get('tier') or TIER_MID
        if tier != current_tier:
            current_tier = tier
            count = sum(1 for x in ordered if (x.get('tier') or TIER_MID) == tier)
            label, color, border = (
                ("상 (핵심 타겟) 🎯", "#c53030", "#e53e3e")
                if tier == TIER_HIGH
                else ("중 (검토 권장) 🔍", "#d69e2e", "#ed8936")
            )
            html += f"""
            <h3 style="font-size: 16px; font-weight: bold; color: {color}; border-bottom: 2px solid {border}; padding-bottom: 6px; margin: 24px 0 16px 0;">
                {label} ({count}건)
            </h3>
            """
        accent = "#e53e3e" if tier == TIER_HIGH else "#ed8936"

        # [FIX] G2B 공고번호도 연도(20xx)로 시작하므로 startswith('20')는 전건 오분류였다.
        # 출처는 수집기가 넣어준 source 필드로만 판정한다.
        is_d2b = (
            'D2B' in str(bid.get('source', '')).upper()
            or '국방' in str(bid.get('order_agency', ''))
        )
        tag_bg = "#ed8936" if is_d2b else "#3182ce"
        tag_text = "D2B 경쟁입찰" if is_d2b else "G2B 일반용역"
        
        # RFP 링크가 있을 경우 추가
        rfp_html = ""
        if bid.get('rfp_file_url'):
            rfp_html = f"""
            <div style="font-size: 13px; color: #4a5568; margin-top: 6px;">
                ♦ <strong>제안요청서(RFP):</strong> <a href="{escape(bid['rfp_file_url'])}" target="_blank" style="color: #e53e3e; font-weight: bold; text-decoration: underline;">[{escape(bid.get('rfp_file_name', '첨부파일 다운로드'))}]</a>
            </div>
            """

        button_html = ""
        if is_d2b:
            button_html = """
            <div style="margin-top: 14px;">
                <a href="https://www.d2b.go.kr" target="_blank" style="background-color: #2d3748; color: #ffffff; padding: 8px 14px; font-size: 12px; font-weight: bold; text-decoration: none; border-radius: 4px; display: inline-block;">
                    D2B 시스템 이동 (공고번호 복사 필수)
                </a>
            </div>
            """
        else:
            bid_url = escape(bid.get('bid_url') or "https://www.g2b.go.kr")
            button_html = f"""
            <div style="margin-top: 14px;">
                <a href="{bid_url}" target="_blank" style="background-color: #3182ce; color: #ffffff; padding: 8px 14px; font-size: 12px; font-weight: bold; text-decoration: none; border-radius: 4px; display: inline-block;">
                    나라장터 공고 바로가기
                </a>
            </div>
            """

        # 비개발자 친화적 요약: 점수/레이어 용어 대신 평문 설명
        def _friendly_summary(tier: str, matched: list, reasons: list) -> str:
            top_kw = " · ".join(matched[:4]) if matched else "관련 키워드"
            has_cross = any("동시출현" in r or "보너스" in r for r in reasons)
            has_agency = any("화이트리스트" in r or "발주기관" in r for r in reasons)
            has_price = any("추정가격" in r or "예산" in r for r in reasons)

            if tier == "상":
                base = "Dabeeo가 수주한 사업과 같은 유형의 공고입니다"
            else:
                base = "Dabeeo 역량과 연관된 공고입니다"

            extras = []
            if has_cross:
                extras.append("영상·AI 역량이 함께 등장해 연관성이 높습니다")
            if has_agency:
                extras.append("Dabeeo와 거래 이력이 있는 발주기관입니다")
            if has_price:
                extras.append("예산 규모가 참여 기준 이상입니다")
            extras.append(f"매칭 키워드: {top_kw}")

            return (base + " — " + " / ".join(extras)) if extras else base

        matched = bid.get('matched') or []
        reasons = bid.get('reasons') or []
        chips = "".join(
            f'<span style="display:inline-block;background:#e6fffa;color:#234e52;'
            f'border:1px solid #b2f5ea;border-radius:10px;font-size:11px;'
            f'padding:1px 7px;margin:0 4px 4px 0;">{escape(k)}</span>'
            for k in matched[:12]
        )
        elig = bid.get('eligibility') or []
        elig_html = ""
        if elig:
            elig_html = (
                '<div style="margin-top:8px;padding:6px 10px;background:#fffaf0;'
                'border:1px solid #fbd38d;border-radius:4px;font-size:12px;color:#7b341e;">'
                '⚠️ <strong>참가자격 확인 필요:</strong> '
                + escape(", ".join(elig))
                + ' — 보유 여부 확인 후 투찰 판단'
                '</div>'
            )

        tier_label = bid.get('tier', '중')
        tier_color = "#276749" if tier_label == "상" else "#744210"
        tier_bg = "#c6f6d5" if tier_label == "상" else "#fefcbf"

        why_html = f"""
    <div style="margin-top: 10px; padding-top: 8px; border-top: 1px dashed #cbd5e0;">
        <div style="font-size: 12px; color: #2d3748; margin-bottom: 6px;">
            <span style="background:{tier_bg};color:{tier_color};font-weight:bold;
                padding:2px 8px;border-radius:4px;margin-right:6px;">
                중요도 {escape(tier_label)}
            </span>
            <strong>이 공고가 뜬 이유</strong>
        </div>
        <div style="margin-bottom:6px;">{chips}</div>
        <div style="font-size: 11px; color: #4a5568; line-height:1.6;">
            {escape(_friendly_summary(tier_label, matched, reasons))}
        </div>
    </div>
"""

        html += f"""
        <div style="background-color: #f7fafc; border-left: 4px solid {accent}; border-radius: 4px; padding: 16px; margin-bottom: 16px;">
            <div style="font-size: 15px; font-weight: bold; color: #1a202c; margin-bottom: 10px;">
                <span style="background-color: {tag_bg}; color: #ffffff; font-size: 11px; padding: 2px 6px; border-radius: 3px; margin-right: 6px; vertical-align: middle;">{tag_text}</span>
                {escape(bid['bid_name'])}
            </div>
            <div style="font-size: 13px; color: #4a5568; margin-bottom: 4px;">
                ♦ <strong>발주기관 및 계약:</strong> {escape(bid['order_agency'])}
            </div>
            <div style="font-size: 13px; color: #4a5568; margin-bottom: 4px;">
                ♦ <strong>지역제한:</strong> <span style="color: #2f855a; font-weight: bold;">{escape(bid.get('region', '국방전용/전국'))}</span> | <strong>공고번호:</strong> <span style="background-color: #edf2f7; padding: 2px 6px; border-radius: 3px; font-family: monospace;">{escape(bid['bid_no'])}</span>
            </div>
            <div style="font-size: 13px; color: #4a5568;">
                ♦ <strong>마감일시:</strong> <span style="color: #e53e3e; font-weight: bold;">{escape(bid.get('bid_date', '진행중'))}</span>
            </div>
            {rfp_html}
            {elig_html}
            {why_html}
            {button_html}
        </div>
        """

    html += """
            </div>
        </div>
    </body>
    </html>
    """
    return html

def send_email_notification(new_bids):
    if not SMTP_USER or not SMTP_PASSWORD or not RECEIVER_EMAIL:
        print("[ERROR] 이메일 환경변수가 지정되지 않았습니다.")
        return

    html_content = build_email_html(new_bids)

    high = sum(1 for b in new_bids if b.get("tier") == TIER_HIGH)
    receivers = RECEIVERS or [e.strip() for e in RECEIVER_EMAIL.split(",") if e.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"[통합 입찰 리포트] 신규 {len(new_bids)}건 (상 {high}건)"
    )
    msg["From"] = formataddr(("Dabeeo Bid Bot", SMTP_USER))
    msg["To"] = ", ".join(receivers)
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, receivers, msg.as_string())
        print(f"[SUCCESS] 이메일 발송 완료 ({len(receivers)}명)")
    except Exception as e:
        print(f"[ERROR] 이메일 발송 실패: {e}")

def notify_new_bids():
    init_db()

    # G2B + D2B 공고 통합 수집
    all_bids = fetch_g2b_bids()
    if fetch_d2b_bids:
        try:
            all_bids.extend(fetch_d2b_bids())
        except Exception as e:
            print(f"[WARN] D2B 수집 에러: {e}")

    # [FIX] 건당 SELECT 루프 → 배치 1회 질의 (테이블 생성/커넥션 관리도 마스터로 이관)
    new_bids = filter_new_bids(all_bids)

    if not new_bids:
        print("신규 공고가 없어 메일을 보낼 건이 없습니다.")
        return

    send_email_notification(new_bids)
    # [FIX] 발송 성공/실패와 무관하게 저장하면 재발송 기회를 잃으므로 발송 후 저장 유지
    save_bids_to_db(new_bids)

if __name__ == "__main__":
    notify_new_bids()
