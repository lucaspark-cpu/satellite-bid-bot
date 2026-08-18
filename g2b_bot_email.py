import os
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dabeeo_bid_master import fetch_g2b_servc_bids, save_bids_to_db, init_db

# 이메일 설정을 위한 환경 변수
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")          # 발신 이메일 주소
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # 발신 계정 앱 비밀번호
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "") # 수신자 이메일 (쉼표로 구분 가능)

def send_email_notification(new_bids):
    """신규 공고 목록을 깔끔한 HTML 이메일 형태로 전송"""
    if not SMTP_USER or not SMTP_PASSWORD or not RECEIVER_EMAIL:
        print("[ERROR] 이메일 발송 환경변수(SMTP_USER, SMTP_PASSWORD, RECEIVER_EMAIL)가 설정되지 않았습니다.")
        return

    # 본문 HTML 구성
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 650px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            🚨 [나라장터] 신규 용역 입찰 공고 ({len(new_bids)}건)
        </h2>
        <p style="color: #555;">키워드(위성, 공간정보, AI, 영상, 다비오) 관련 신규 입찰 공고가 등록되었습니다.</p>
    """

    for bid in new_bids:
        rfp_html = ""
        if bid.get('rfp_file_url'):
            rfp_html = f"""
            <p style="margin: 5px 0;">
                <b>첨부문서:</b> <a href="{bid['rfp_file_url']}" style="color: #d93025; font-weight: bold; text-decoration: none;">📄 {bid.get('rfp_file_name', '제안요청서 다운로드')}</a>
            </p>
            """

        html_content += f"""
        <div style="margin-bottom: 20px; padding: 15px; background-color: #f8f9fa; border-left: 4px solid #1a73e8; border-radius: 4px;">
            <h3 style="margin-top: 0; color: #202124;">{bid['bid_name']}</h3>
            <p style="margin: 5px 0; color: #3c4043;"><b>발주기관:</b> {bid['order_agency']}</p>
            <p style="margin: 5px 0; color: #3c4043;"><b>공고번호:</b> {bid['bid_no']}</p>
            <p style="margin: 5px 0; color: #3c4043;"><b>게시일시:</b> {bid['bid_date']}</p>
            {rfp_html}
            <div style="margin-top: 12px;">
                <a href="{bid['bid_url']}" style="background-color: #1a73e8; color: white; padding: 8px 14px; text-decoration: none; border-radius: 4px; font-size: 14px; display: inline-block;">공고 바로가기</a>
            </div>
        </div>
        """

    html_content += """
        <hr style="border: none; border-top: 1px solid #eee; margin-top: 30px;">
        <p style="font-size: 12px; color: #888; text-align: center;">본 메일은 GitHub Actions 자동화 시스템을 통해 발송되었습니다.</p>
    </div>
    """

    # 이메일 메타데이터 구성
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[나라장터 알림] 신규 입찰 공고 {len(new_bids)}건이 등록되었습니다."
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
        print(f"[SUCCESS] {len(receivers)}명의 수신자에게 이메일 알림 전송 완료!")
    except Exception as e:
        print(f"[ERROR] 이메일 발송 실패: {e}")

def notify_new_bids():
    init_db()
    bids = fetch_g2b_servc_bids()
    
    conn = sqlite3.connect("g2b_bids.db")
    cursor = conn.cursor()
    
    new_bids = []
    for bid in bids:
        cursor.execute("SELECT bid_no FROM bids WHERE bid_no = ?", (bid['bid_no'],))
        if not cursor.fetchone():
            new_bids.append(bid)

    if not new_bids:
        print("신규 공고가 없습니다.")
        return

    # 신규 공고 이메일 발송
    send_email_notification(new_bids)

    # DB 저장 (중복 발송 방지)
    save_bids_to_db(new_bids)

if __name__ == "__main__":
    notify_new_bids()
