# g2b_bot.py
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# 1. 이메일 발송 설정 정보 (★ 본인 정보로 채워 넣으세요)
SENDER_EMAIL = 'lucas.park@dabeeo.com'
SENDER_PASSWORD = 'yxph vbqx puco byut' # 공백 없이 입력
RECEIVER_EMAIL = 'lucas.park@dabeeo.com'

SERVICE_KEY = '+emmedaZrwpwK2FqtKT9BiUA9/qWfUYkm3pFh/w95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg=='
SEARCH_KEYWORD = '위성', '영상', '분석'
API_URL = 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch'

# 이메일 발송 함수
def send_email(subject, content):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = subject
        
        # HTML 형식으로 이메일 본문 작성 (이메일이 훨씬 깔끔하게 보입니다)
        msg.attach(MIMEText(content, 'html', 'utf-8'))
        
        # 지메일 SMTP 서버 연결
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls() # 보안 연결
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print("✅ 이메일 발송 성공!")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

# 2. 날짜 계산 (최근 7일)
today = datetime.now()
seven_days_ago = today - timedelta(days=7)
inqry_bgn_dt = seven_days_ago.strftime('%Y%m%d0000')
inqry_end_dt = today.strftime('%Y%m%d2359')

params = {
    'ServiceKey': SERVICE_KEY,
    'type': 'json',               
    'numOfRows': '50',            
    'pageNo': '1',                
    'inqryDiv': '1',              
    'inqryBgnDt': inqry_bgn_dt,   
    'inqryEndDt': inqry_end_dt,   
    'bidNtceNm': SEARCH_KEYWORD,  
    'bidClseExcpYn': 'Y'          
}

response = requests.get(API_URL, params=params)

if response.status_code == 200:
    data = response.json()
    try:
        total_count = data['response']['body']['totalCount']
        items = data['response']['body']['items']
        items = sorted(items, key=lambda x: x.get('bidNtceDt', ''), reverse=True)
        
        # 이메일 제목 및 HTML 본문 디자인 구성
        subject = f"📢 [나라장터] '{SEARCH_KEYWORD}' 관련 신규 입찰공고 리포트"
        
        html_content = f"""
        <html>
        <body>
            <h2>🚀 나라장터 [{SEARCH_KEYWORD}] 관련 신규 용역 공고</h2>
            <p>최근 일주일간 등록된 진행 중인 공고가 총 <b>{total_count}건</b> 검색되었습니다.</p>
            <hr>
        """
        
        for idx, item in enumerate(items, 1):
            html_content += f"""
            <div style='margin-bottom: 20px; padding: 10px; border-left: 4px solid #3498db; background-f9f9f9;'>
                <h3 style='margin: 0 0 10px 0; color: #2c3e50;'>{idx}. {item.get('bidNtceNm', '공고명 없음')}</h3>
                <p style='margin: 5px 0;'><b>🔹 수요기관:</b> {item.get('dminsttNm', '-')}</p>
                <p style='margin: 5px 0;'><b>🔹 공고일시:</b> {item.get('bidNtceDt', '-')}</p>
                <p style='margin: 5px 0;'><b>🔹 마감일시:</b> <span style='color: #e74c3c;'>{item.get('bidClseDt', '-')}</span></p>
                <p style='margin: 10px 0 0 0;'><a href='{item.get('bidNtceUrl', '-')}' target='_blank' style='background-color: #3498db; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;'>공고 상세 보기</a></p>
            </div>
            """
            
        html_content += "</body></html>"
        send_email(subject, html_content)
        
    except KeyError:
        subject = f"ℹ️ [나라장터] '{SEARCH_KEYWORD}' 관련 신규 공고 없음"
        html_content = f"<h3>최근 일주일 내에 등록된 '{SEARCH_KEYWORD}' 관련 신규 용역 공고가 없습니다.</h3>"
        send_email(subject, html_content)
