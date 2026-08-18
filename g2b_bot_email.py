import os
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 기존 수집 모듈에서 G2B 및 D2B 함수 불러오기
from dabeeo_bid_master import fetch_g2b_servc_bids, save_bids_to_db, init_db
try:
    from dabeeo_bid_master import fetch_d2b_bids  # D2B 수집 함수가 있을 경우
except ImportError:
    fetch_d2b_bids = None

# 이메일 환경변수
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "")

def send_email_notification(new_bids):
    if not SMTP_USER or not SMTP_PASSWORD or not RECEIVER_EMAIL:
        print("[ERROR] 이메일 발송 환경변수가 세팅되지 않았습니다.")
        return

    # 기존 카드 형태의 이메일 HTML 디자인
    html_content = f"""
    <div style="font-family: 'Apple SD Gothic Neo', '맑은 고딕', sans-serif; max-width: 650px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px; margin-top: 0;">
            📢 [입찰 공고 알림] 신규 공고 {len(new_bids)}건 발굴
        </h2>
        <p style="color: #555; font-size: 14px;">수집된 신규 입찰 공고 목록입니다.</p>
    """

    for bid in new_bids:
        rfp_html = ""
        if bid.get('rfp_file_url'):
            rfp_html = f"""
            <p style="margin: 6px 0; font-size: 13px;">
                <b>📄 제안요청서:</b> <a href="{bid['rfp_file_url']}" style="color: #d93025; font-weight: bold; text-decoration: none;">[{bid.get('rfp_file_name', '첨부파일 다운로드')}]</a>
            </p>
            """

        html_content += f"""
        <div style="margin-bottom: 15px; padding: 15px; background-color: #f8f9fa; border-left: 4px solid #1a73e8; border-radius: 4px;">
            <h3 style="margin: 0 0 10px 0; color: #202124; font-size: 16px;">{bid['bid_name']}</h3>
            <p style="margin: 4px 0; font-size: 13px; color: #3c4043;"><b>발주기관:</b> {bid['order_agency']}</p>
            <p style="margin: 4px 0; font-size: 13px; color: #3c4043;"><b>공고번호:</b> {bid['bid_no']}</p>
            <p style="margin: 4px 0; font-size: 13px; color: #3c4043;"><b>게시일시:</b> {bid['bid_date']}</p>
            {rfp_html}
            <div style="margin-top: 10px;">
                <a href="{bid['bid_url']}" style="background-color: #1a73e8; color: white; padding: 6px 12px; text-decoration: none; border-radius: 4px; font-size: 13px; display: inline-block;">공고 바로가기</a>
            </div>
        </div>
        """

    html_content += """
        <hr style="border: none; border-top: 1px solid #eee; margin-top: 25px;">
        <p style="font-size: 11px; color: #888; text-align: center;">본 메일은 satellite-bid-bot 자동화 시스템을 통해 발송되었습니다.</p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[입찰 알림] 신규 입찰 공고 {len(new_bids)}건이 등록되었습니다."
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
        print(f"[SUCCESS] {len(receivers)}명에게 이메일 전송 완료")
    except Exception as e:
        print(f"[ERROR] 이메일 발송 실패: {e}")

def notify_new_bids():
    init_db()
    
    # 1. G2B(나라장터) 수집
    all_bids = fetch_g2b_servc_bids()
    
    # 2. D2B(국방전자조달) 수집 함수가 존재하는 경우 통합
    if fetch_d2b_bids:
        try:
            d2b_bids = fetch_d2b_bids()
            all_bids.extend(d2b_bids)
        except Exception as e:
            print(f"[WARN] D2B 수집 중 오류: {e}")

    conn = sqlite3.connect("g2b_bids.db")
    cursor = conn.cursor()
    
    new_bids = []
    for bid in all_bids:
        cursor.execute("SELECT bid_no FROM bids WHERE bid_no = ?", (bid['bid_no'],))
        if not cursor.fetchone():
            new_bids.append(bid)

    if not new_bids:
        print("신규 공고가 없어 메일을 발송하지 않았습니다.")
        return

    send_email_notification(new_bids)
    save_bids_to_db(new_bids)

if __name__ == "__main__":
    notify_new_bids()
