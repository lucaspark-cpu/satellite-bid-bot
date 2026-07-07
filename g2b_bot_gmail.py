# g2b_bot_gmail.py
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# 1. 이메일 발송 설정 정보
SENDER_EMAIL = 'lucas.park@dabeeo.com'
SENDER_PASSWORD = 'yxphvbqxpucobyut' 

# 변수명을 RECEIVER_LIST로 정의합니다.
RECEIVER_LIST = [
    'lucas.park@dabeeo.com',
    'joohyeon.kim@dabeeo.com'
]

# 이제 정상적으로 RECEIVER_LIST를 조합하여 RECEIVER_EMAIL을 만듭니다.
RECEIVER_EMAIL = ", ".join(RECEIVER_LIST)

SERVICE_KEY = '+emmedaZrwpwK2FqtKT9BiUA9/qWfUYkm3pFh/w95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg=='
API_URL = 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch'

# 💡 튜플이 아닌 개별 키워드 리스트로 관리하여 루프를 돌립니다.
KEYWORDS = ['위성', '영상', '분석']

# 이메일 발송 함수
def send_email(subject, content):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = subject
        
        msg.attach(MIMEText(content, 'html', 'utf-8'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
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

# 3. 키워드별 순회 검색 및 중복 제거 로직
unique_items = {} # 공고번호(bidNtceNo)를 key로 사용하여 중복 제거

for keyword in KEYWORDS:
    params = {
        'ServiceKey': SERVICE_KEY,
        'type': 'json',               
        'numOfRows': '50',            
        'pageNo': '1',                
        'inqryDiv': '1',              
        'inqryBgnDt': inqry_bgn_dt,   
        'inqryEndDt': inqry_end_dt,   
        'bidNtceNm': keyword,         # 개별 키워드 순차 대입
        'bidClseExcpYn': 'Y'          
    }
    
    response = requests.get(API_URL, params=params)
    
    if response.status_code == 200:
        try:
            data = response.json()
            items = data['response']['body']['items']
            
            # 리스트 데이터가 한 건일 경우 딕셔너리로 반환되는 예외 대응
            if isinstance(items, dict):
                items = [items]
                
            for item in items:
                notice_no = item.get('bidNtceNo')
                if notice_no:
                    unique_items[notice_no] = item # 중복된 공고는 덮어씌워져 1건만 남음
        except KeyError:
            continue

# 4. 결과 통합 및 정렬
final_items = list(unique_items.values())
final_items = sorted(final_items, key=lambda x: x.get('bidNtceDt', ''), reverse=True)
total_count = len(final_items)

# 5. 이메일 본문 생성 및 발송
keyword_str = ", ".join(KEYWORDS)

# 💡 주석이나 마크다운 기호 없이 딱 아래 한 줄만 들어가야 합니다!
subject = "📢 [나라장터] '위성/영상/분석' 관련 신규 입찰공고 리포트"

if total_count > 0:
    html_content = f"""
    <html>
    <body>
        <h2>🚀 나라장터 검색 알림 (검색어: {keyword_str})</h2>
        <p>최근 일주일간 등록된 진행 중인 공고가 중복 없이 총 <b>{total_count}건</b> 검색되었습니다.</p>
        <hr>
    """
    
    for idx, item in enumerate(final_items, 1):
        # 💡 background 문법 오류 수정 완료
        html_content += f"""
        <div style='margin-bottom: 20px; padding: 10px; border-left: 4px solid #3498db; background-color: #f9f9f9;'>
            <h3 style='margin: 0 0 10px 0; color: #2c3e50;'>{idx}. {item.get('bidNtceNm', '공고명 없음')}</h3>
            <p style='margin: 5px 0;'><b>🔹 수요기관:</b> {item.get('dminsttNm', '-')}</p>
            <p style='margin: 5px 0;'><b>🔹 공고일시:</b> {item.get('bidNtceDt', '-')}</p>
            <p style='margin: 5px 0;'><b>🔹 마감일시:</b> <span style='color: #e74c3c;'>{item.get('bidClseDt', '-')}</span></p>
            <p style='margin: 10px 0 0 0;'><a href='{item.get('bidNtceUrl', '-')}' target='_blank' style='background-color: #3498db; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;'>공고 상세 보기</a></p>
        </div>
        """
    html_content += "</body></html>"
else:
    html_content = f"<h3>최근 일주일 내에 등록된 '{keyword_str}' 관련 신규 용역 공고가 없습니다.</h3>"

send_email(subject, html_content)
