import os
import requests
import urllib.parse
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET

def get_defense_bids(service_key):
    end_date = datetime.now().strftime("%Y%m%d")
    begin_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    
    keyword_encoded = urllib.parse.quote("위성")
    operation_name = "getDmstcCmpetBidPblancList"
    url = (
        f"https://apis.data.go.kr/1690000/BidPblancInfoService/{operation_name}"
        f"?serviceKey={service_key}"
        f"&pageNo=1"
        f"&numOfRows=5"
        f"&opengDateBegin={begin_date}"
        f"&opengDateEnd={end_date}"
        f"&bidNm={keyword_encoded}"
    )
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return parse_bids_xml(response.text)
        return f"<p style='color:red;'>API 호출 실패 (HTTP {response.status_code})</p>"
    except Exception as e:
        return f"<p style='color:red;'>API 연결 오류: {str(e)}</p>"

def parse_bids_xml(xml_text):
    try:
        root = ET.fromstring(xml_text)
        items = root.findall('.//item')
        if not items:
            return "<p>최근 3개월간 '위성' 관련 국내 경쟁입찰공고가 없습니다.</p>"
        
        html = "<table border='1' style='border-collapse:collapse; width:100%; text-align:left;'>"
        html += "<tr style='background-color:#f2f2f2;'><th>공고명</th><th>공고기관</th><th>계약방식</th><th>개찰일시</th></tr>"
        for item in items:
            bid_nm = item.findtext('bidNm', 'N/A')
            ornt = item.findtext('ornt', 'N/A')
            cntrctMth = item.findtext('cntrctMth', 'N/A')
            opengDt = item.findtext('opengDt', 'N/A')
            
            # 날짜 포맷팅 (202603061030 -> 2026-03-06 10:30)
            if len(opengDt) == 12:
                opengDt = f"{opengDt[0:4]}-{opengDt[4:6]}-{opengDt[6:8]} {opengDt[8:10]}:{opengDt[10:12]}"
                
            html += f"<tr><td>{bid_nm}</td><td>{ornt}</td><td>{cntrctMth}</td><td>{opengDt}</td></tr>"
        html += "</table>"
        return html
    except Exception as e:
        return f"<p style='color:red;'>XML 파싱 오류: {e}</p>"

def send_email(bi_html_content):
    spreadsheet_id = os.environ.get('SPREADSHEET_ID') # 기존 전역변수 호출용 변환
    sender_email = os.environ.get('TOKEN_REPAIR') # 본래 토큰 용도이나 예시 구조에 맞춤 (실제 구글 계정 ID 권장)
    
    # 만약 환경변수 세팅이 안 되어 있다면 본인 메일 주소를 기본값으로 안전장치
    if not sender_email or "@" not in sender_email:
        sender_email = "your_email@gmail.com" 

    # 💡 [핵심 수정] 환경변수나 입력값에서 수신자 목록을 가져옵니다.
    raw_receiver = os.environ.get("RECEIVER_EMAIL", "").strip()
    
    # 쉼표(,)를 기준으로 쪼개고, 각 주소의 공백이나 기호(***)를 청소합니다.
    receiver_list = []
    if raw_receiver:
        for email in raw_receiver.split(","):
            clean_email = email.replace("*", "").strip()
            if clean_email:
                receiver_list.append(clean_email)
                
    # 만약 입력된 수신자가 하나도 없다면 나 자신에게 보냅니다.
    if not receiver_list:
        receiver_list = [sender_email]
        
    smtp_host = "smtp.gmail.com"
    smtp_port = 587
    sender_password = os.environ.get("SMTP_PASSWORD")
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🚀 [신안보 Intelligence] {datetime.now().strftime('%Y-%m-%d')} 일일 공동 브리핑"
    msg['From'] = sender_email
    msg['To'] = ", ".join(receiver_list) # 메일 헤더에는 "aaa@com, bbb@com" 형태의 문자열로 입력
    
    html_body = f"""
    <html>
    <body>
        <h2>🛡️ 신안보 9시 테크-브리핑</h2>
        <p>본 메일은 정부의 미래 신안보 혁신기업 육성 방향 및 글로벌 시장 동향을 반영한 자동화 브리핑입니다.</p>
        <hr>
        
        <h3>1. 방위사업청 '위성' 관련 최신 입찰 공고 (최근 90일)</h3>
        {bi_html_content}
        
        <hr>
        <h3>2. 오늘의 신안보 핵심 Intelligence 요약</h3>
        <ul>
            <li><b>K-팔란티어 육성 본격화:</b> 중기부·국방부·우주청 중심 10조 원 규모 미래전략기술 펀드 조성 및 한국형 인큐텔(IQT) 신설 추진 중</li>
            <li><b>소프트웨어 정의 전장(Software-defined Warfare):</b> 미국 안두릴(Anduril)의 래티스 OS, 팔란티어 AIP 등 AI 기반 의사결정체계가 핵심 Moat로 부상</li>
            <li><b>상업 위성 기술의 전장 활용:</b> AI 기반 위성 영상 분석(다비오의 어스아이, 중국 미자르비전 등)이 실시간 킬체인 단축의 핵심 열쇠로 작동</li>
        </ul>
        <br>
        <p style='font-size:11px; color:gray;'>본 메일은 GitHub Actions를 통해 자동 발송됩니다.</p>
    </body>
    </html>
    """
    
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        # 💡 [핵심 수정] 구글 서버에는 수신자 '리스트'를 그대로 넘겨주어야 동시 발송됩니다.
        server.sendmail(sender_email, receiver_list, msg.as_string())
        
    print(f"✅ 동시 발송 완료! 대상자 목록: {receiver_list}")

if __name__ == "__main__":
    api_key = os.environ.get("DATA_GO_KR_API_KEY")
    bids_data = get_defense_bids(api_key)
    send_email(bids_data)
