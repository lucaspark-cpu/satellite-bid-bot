import os
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dabeeo_bid_master import fetch_g2b_servc_bids, save_bids_to_db, init_db
try:
    from dabeeo_bid_master import fetch_d2b_bids
except ImportError:
    fetch_d2b_bids = None

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "")

# 검색 키워드 표시용
SEARCH_KEYWORDS_STR = "위성, 공간정보, AI, 드론, 영상, 모니터링, 변화"

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

            <!-- 공고 섹션 타이틀 -->
            <h3 style="font-size: 16px; font-weight: bold; color: #d69e2e; border-bottom: 2px solid #ed8936; padding-bottom: 6px; margin-bottom: 16px;">
                중 (검토 권장) 🔍 ({total_count}건)
            </h3>

            <!-- 공고 카드 목록 -->
            <div>
    """

    for bid in bids:
        is_d2b = bid.get('bid_no', '').startswith('20') or 'D2B' in bid.get('source', '') or '국방' in bid.get('order_agency', '')
        tag_bg = "#ed8936" if is_d2b else "#3182ce"
        tag_text = "D2B 경쟁입찰" if is_d2b else "G2B 일반용역"
        
        # RFP 링크가 있을 경우 추가
        rfp_html = ""
        if bid.get('rfp_file_url'):
            rfp_html = f"""
            <div style="font-size: 13px; color: #4a5568; margin-top: 6px;">
                ♦ <strong>제안요청서(RFP):</strong> <a href="{bid['rfp_file_url']}" target="_blank" style="color: #e53e3e; font-weight: bold; text-decoration: underline;">[{bid.get('rfp_file_name', '첨부파일 다운로드')}]</a>
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
            bid_url = bid.get('bid_url') or "https://www.g2b.go.kr"
            button_html = f"""
            <div style="margin-top: 14px;">
                <a href="{bid_url}" target="_blank" style="background-color: #3182ce; color: #ffffff; padding: 8px 14px; font-size: 12px; font-weight: bold; text-decoration: none; border-radius: 4px; display: inline-block;">
                    나라장터 공고 바로가기
                </a>
            </div>
            """

        html += f"""
        <div style="background-color: #f7fafc; border-left: 4px solid #ed8936; border-radius: 4px; padding: 16px; margin-bottom: 16px;">
            <div style="font-size: 15px; font-weight: bold; color: #1a202c; margin-bottom: 10px;">
                <span style="background-color: {tag_bg}; color: #ffffff; font-size: 11px; padding: 2px 6px; border-radius: 3px; margin-right: 6px; vertical-align: middle;">{tag_text}</span>
                {bid['bid_name']}
            </div>
            <div style="font-size: 13px; color: #4a5568; margin-bottom: 4px;">
                ♦ <strong>발주기관 및 계약:</strong> {bid['order_agency']}
            </div>
            <div style="font-size: 13px; color: #4a5568; margin-bottom: 4px;">
                ♦ <strong>지역제한:</strong> <span style="color: #2f855a; font-weight: bold;">{bid.get('region', '국방전용/전국')}</span> | <strong>공고번호:</strong> <span style="background-color: #edf2f7; padding: 2px 6px; border-radius: 3px; font-family: monospace;">{bid['bid_no']}</span>
            </div>
            <div style="font-size: 13px; color: #4a5568;">
                ♦ <strong>마감일시:</strong> <span style="color: #e53e3e; font-weight: bold;">{bid.get('bid_date', '진행중')}</span>
            </div>
            {rfp_html}
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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 [통합 입찰 리포트] 신규 입찰 공고 {len(new_bids)}건이 분류되었습니다."
    msg["From"] = SMTP_USER
    msg["To"] = RECEIVER_EMAIL
    msg.attach(MIMEText(html_content, "html"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        receivers = [e.strip() for e in RECEIVER_EMAIL.split(",")]
        server.sendmail(SMTP_USER, receivers, msg.as_string())
        server.quit()
        print(f"[SUCCESS] 이메일 발송 완료 ({len(receivers)}명)")
    except Exception as e:
        print(f"[ERROR] 이메일 발송 실패: {e}")

def notify_new_bids():
    init_db()
    
    # G2B + D2B 공고 통합 수집
    all_bids = fetch_g2b_servc_bids()
    if fetch_d2b_bids:
        try:
            d2b_bids = fetch_d2b_bids()
            all_bids.extend(d2b_bids)
        except Exception as e:
            print(f"[WARN] D2B 수집 에러: {e}")

    conn = sqlite3.connect("g2b_bids.db")
    cursor = conn.cursor()
    
    new_bids = []
    for bid in all_bids:
        cursor.execute("SELECT bid_no FROM bids WHERE bid_no = ?", (bid['bid_no'],))
        if not cursor.fetchone():
            new_bids.append(bid)

    if not new_bids:
        print("신규 공고가 없어 메일을 보낼 건이 없습니다.")
        return

    send_email_notification(new_bids)
    save_bids_to_db(new_bids)

if __name__ == "__main__":
    notify_new_bids()
