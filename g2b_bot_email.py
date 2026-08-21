import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dabeeo_bid_master import fetch_g2b_servc_bids, fetch_d2b_bids

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "")

SEARCH_KEYWORDS_STR = "위성, 공간정보, AI, 드론, 영상, 모니터링, 변화탐지, 국방"

def build_email_html(bids: list) -> str:
    """HTML 메일 양식 생성"""
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
            <h2 style="font-size: 22px; font-weight: bold; color: #1a202c; margin-bottom: 12px;">
                🚀 나라장터 및 국방전자조달 통합 인텔리전스
            </h2>
            <p style="font-size: 14px; color: #4a5568; margin-top: 0; margin-bottom: 8px;">
                다비오 비즈니스 도메인 연관도 스코어링 알고리즘에 따라 총 <strong style="color: #d69e2e;">{total_count}건</strong>의 진행 중인 유효 공고가 분류되었습니다.
            </p>
            <p style="font-size: 13px; color: #718096; margin-top: 0; margin-bottom: 24px;">
                주요 타겟 키워드: {SEARCH_KEYWORDS_STR}
            </p>

            <!-- 활용 가이드 박스 -->
            <div style="background-color: #f0f7ff; border: 1px solid #c3e0ff; border-radius: 8px; padding: 18px 20px; margin-bottom: 28px;">
                <h4 style="font-size: 15px; font-weight: bold; color: #1a365d; margin: 0 0 12px 0;">
                    💡 리포트 활용 가이드
                </h4>
                <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: #2d3748; line-height: 1.8;">
                    <li style="margin-bottom: 6px;">
                        🎯 <strong>맞춤 가중치 정렬:</strong> '위성', '공간정보', 'AI 객체식별', '변화탐지' 등 다비오 핵심 사업 영역 키워드와 조합에 따라 가중 점수가 부여되었습니다.
                    </li>
                    <li style="margin-bottom: 6px;">
                        🛡️ <strong>D2B 공고 검색:</strong> 국방전자조달 공고는 보안상 '공고번호'를 복사하여 <a href="https://www.d2b.go.kr" target="_blank" style="color: #e53e3e; font-weight: bold;">D2B 메인페이지</a>에서 검색하여 조회할 수 있습니다.
                    </li>
                </ul>
            </div>

            <h3 style="font-size: 16px; font-weight: bold; color: #d69e2e; border-bottom: 2px solid #ed8936; padding-bottom: 6px; margin-bottom: 16px;">
                유효 진행 공고 리스트 ({total_count}건)
            </h3>

            <div>
    """

    for bid in bids:
        is_d2b = bid.get('bid_no', '').startswith('20') or 'D2B' in bid.get('source', '')
        tag_bg = "#ed8936" if is_d2b else "#3182ce"
        tag_text = "D2B 경쟁입찰" if is_d2b else "G2B 일반용역"
        
        button_html = f"""
        <div style="margin-top: 14px;">
            <a href="{bid.get('bid_url', 'https://www.g2b.go.kr')}" target="_blank" style="background-color: {tag_bg}; color: #ffffff; padding: 8px 14px; font-size: 12px; font-weight: bold; text-decoration: none; border-radius: 4px; display: inline-block;">
                {tag_text} 바로가기
            </a>
        </div>
        """

        html += f"""
        <div style="background-color: #f7fafc; border-left: 4px solid {tag_bg}; border-radius: 4px; padding: 16px; margin-bottom: 16px;">
            <div style="font-size: 15px; font-weight: bold; color: #1a202c; margin-bottom: 10px;">
                <span style="background-color: {tag_bg}; color: #ffffff; font-size: 11px; padding: 2px 6px; border-radius: 3px; margin-right: 6px; vertical-align: middle;">{tag_text}</span>
                [{bid.get('score', 0)}점] {bid['bid_name']}
            </div>
            <div style="font-size: 13px; color: #4a5568; margin-bottom: 4px;">
                ♦ <strong>발주기관:</strong> {bid['order_agency']}
            </div>
            <div style="font-size: 13px; color: #4a5568; margin-bottom: 4px;">
                ♦ <strong>지역제한:</strong> <span style="color: #2f855a; font-weight: bold;">{bid.get('region', '전국')}</span> | <strong>공고번호:</strong> <span style="background-color: #edf2f7; padding: 2px 6px; border-radius: 3px; font-family: monospace;">{bid['bid_no']}</span>
            </div>
            <div style="font-size: 13px; color: #4a5568;">
                ♦ <strong>마감일시:</strong> <span style="color: #e53e3e; font-weight: bold;">{bid.get('bid_date', '진행중')}</span>
            </div>
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

def send_email_notification(bids: list):
    if not SMTP_USER or not SMTP_PASSWORD or not RECEIVER_EMAIL:
        print("[ERROR] 이메일 설정(SMTP_USER, SMTP_PASSWORD, RECEIVER_EMAIL)을 확인해주세요.")
        return

    html_content = build_email_html(bids)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚀 [다비오 입찰 알림] 진행 중인 유효 공고 {len(bids)}건이 수집되었습니다."
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
        print(f"[SUCCESS] 이메일 발송 완료 ({len(receivers)}명 대상)")
    except Exception as e:
        print(f"[ERROR] 이메일 발송 실패: {e}")

def notify_new_bids():
    # DB 중복 체크 제거: G2B + D2B 유효 공고 전체 수집 후 발송
    all_bids = fetch_g2b_servc_bids()
    if fetch_d2b_bids:
        try:
            d2b_bids = fetch_d2b_bids()
            all_bids.extend(d2b_bids)
        except Exception as e:
            print(f"[WARN] D2B 수집 에러: {e}")

    if not all_bids:
        print("조건에 맞는 마감 전 유효 공고가 없어 메일을 보낼 건이 없습니다.")
        return

    send_email_notification(all_bids)

if __name__ == "__main__":
    notify_new_bids()
