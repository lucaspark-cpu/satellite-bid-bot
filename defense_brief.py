import os
import requests
import urllib.parse
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET

# ==========================================
# 1. 다비오(Dabeeo) 맞춤형 알고리즘 세팅
# ==========================================
NEGATIVE_KEYWORDS = ["탑재체", "제조", "양산", "부품", "수리", "정비", "기체", "배터리", "하드웨어", "발사체", "엔진", "단말기", "케이블", "안테나"]
HIGH_WEIGHT_KEYWORDS = ["영상", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제"]
MID_WEIGHT_KEYWORDS = ["위성", "드론", "무인기", "정찰", "감시", "시스템", "활용방안", "연구", "정보"]

def evaluate_bid(title):
    """
    공고명(title)을 분석하여 다비오 사업 연관도를 상/중/하로 판별합니다.
    """
    # 1. 네거티브 필터링 (하드웨어, 단순 제조/수리 배제)
    for nk in NEGATIVE_KEYWORDS:
        if nk in title:
            return -1, "제외"

    score = 0
    # 2. 가중치 점수 산정
    for hk in HIGH_WEIGHT_KEYWORDS:
        if hk in title:
            score += 30
    for mk in MID_WEIGHT_KEYWORDS:
        if mk in title:
            score += 15

    # 3. 등급 판정
    if score >= 50:
        return score, "상 (핵심 타겟) 🎯"
    elif score >= 20:
        return score, "중 (검토 권장) 🔍"
    else:
        return score, "하 (단순 키워드) 💡"

# ==========================================
# 2. D2B 국방전자조달 데이터 수집 및 가공
# ==========================================
def get_defense_bids(service_key):
    # 주말을 고려해 최근 7일치 데이터를 넓게 긁어옵니다.
    end_date = datetime.now().strftime("%Y%m%d")
    begin_date = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    
    # 1. 단일 키워드 한계를 극복하기 위한 다중 키워드 수집망
    search_keywords = ["위성", "영상", "드론", "AI", "공간", "데이터"]
    raw_bids = {} # 중복 제거를 위한 딕셔너리

    for keyword in search_keywords:
        keyword_encoded = urllib.parse.quote(keyword)
        url = (
            f"https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcCmpetBidPblancList"
            f"?serviceKey={service_key}"
            f"&pageNo=1"
            f"&numOfRows=50" # 넉넉하게 추출
            f"&opengDateBegin={begin_date}"
            f"&opengDateEnd={end_date}"
            f"&bidNm={keyword_encoded}"
        )
        
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                root = ET.fromstring(response.text)
                items = root.findall('.//item')
                
                for item in items:
                    bid_nm = item.findtext('bidNm', 'N/A')
                    g2b_no = item.findtext('g2bPblancNo', '').strip()
                    bid_id = g2b_no if g2b_no else bid_nm # 고유 ID 지정
                    
                    if bid_id not in raw_bids:
                        raw_bids[bid_id] = {
                            'bidNm': bid_nm,
                            'ornt': item.findtext('ornt', 'N/A'),
                            'cntrctMth': item.findtext('cntrctMth', 'N/A'),
                            'opengDt': item.findtext('opengDt', 'N/A'),
                            'g2bPblancNo': g2b_no
                        }
        except Exception as e:
            print(f"API 호출 오류 ({keyword}): {e}")

    # ==========================================
    # 3. 알고리즘 스크리닝 및 상/중/하 분류
    # ==========================================
    categorized_bids = {"상 (핵심 타겟) 🎯": [], "중 (검토 권장) 🔍": [], "하 (단순 키워드) 💡": []}
    
    for bid_id, data in raw_bids.items():
        score, grade = evaluate_bid(data['bidNm'])
        if score != -1: # 네거티브 필터링 통과한 건만 추가
            categorized_bids[grade].append(data)

    return generate_html_report(categorized_bids)

def generate_html_report(categorized_bids):
    total_valid = sum(len(bids) for bids in categorized_bids.values())
    
    if total_valid == 0:
        return "<p>최근 7일간 다비오 사업모델과 매칭되는 유효 공고가 없습니다.</p>"

    html = ""
    # 등급별 테이블 생성
    for grade in ["상 (핵심 타겟) 🎯", "중 (검토 권장) 🔍", "하 (단순 키워드) 💡"]:
        bids = categorized_bids[grade]
        if not bids:
            continue
            
        color = "#ff4d4d" if "상" in grade else "#ff9900" if "중" in grade else "#0066cc"
        html += f"<h4 style='color:{color}; margin-top:20px;'>{grade} ({len(bids)}건)</h4>"
        html += "<table border='1' style='border-collapse:collapse; width:100%; text-align:left; font-family:Arial, sans-serif; font-size:13px;'>"
        html += "<tr style='background-color:#f2f2f2; height:30px;'><th>공고명</th><th>공고기관</th><th>계약방식</th><th>개찰일시</th><th>국방조달</th></tr>"
        
        for data in bids:
            g2b_no = data['g2bPblancNo']
            link_html = f"<a href='https://www.d2b.go.kr/' target='_blank' style='color:#0066cc; text-decoration:underline;'>D2B이동<br><span style='font-size:10px;'>({g2b_no})</span></a>" if g2b_no else "D2B이동"
            
            openg_dt = data['opengDt']
            if len(openg_dt) == 12:
                openg_dt = f"{openg_dt[4:6]}-{openg_dt[6:8]} {openg_dt[8:10]}:{openg_dt[10:12]}"
                
            html += f"<tr style='height:35px;'><td>{data['bidNm']}</td><td>{data['ornt']}</td><td>{data['cntrctMth']}</td><td>{openg_dt}</td><td style='text-align:center;'>{link_html}</td></tr>"
        html += "</table>"
        
    return html

# ==========================================
# 4. 이메일 발송
# ==========================================
def send_email(bid_html):
    sender_email = os.environ.get("SMTP_EMAIL", "lucas.park@dabeeo.com")
    sender_password = os.environ.get("SMTP_PASSWORD")
    
    raw_receiver = os.environ.get("RECEIVER_EMAIL", "").strip()
    receiver_list = [email.replace("*", "").strip() for email in raw_receiver.split(",") if email.replace("*", "").strip()]
    if not receiver_list:
        receiver_list = ["lucas.park@dabeeo.com", "joohyeon.kim@dabeeo.com"]
        
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🚀 [Dabeeo D2B 맞춤형] {datetime.now().strftime('%Y-%m-%d')} 신안보 공고 스크리닝"
    msg['From'] = sender_email
    msg['To'] = ", ".join(receiver_list)
    
    html_body = f"""
    <html>
    <body style='font-family: Arial, sans-serif; line-height: 1.6; color: #333;'>
        <h2>🛡️ 다비오(Dabeeo) 맞춤형 신안보 테크-브리핑</h2>
        <p>단순 하드웨어 및 제조 공고는 <b>자동 필터링(제외)</b>되었으며, 다비오의 핵심 역량(AI, 공간정보, 영상분석)에 가중치를 부여해 연관도 순으로 정렬했습니다.</p>
        
        <div style='background-color: #f4f7fa; border-left: 5px solid #0066cc; padding: 12px; margin-bottom: 20px; font-size: 13px;'>
            📌 <b>국방전자조달(D2B) 조회 가이드</b><br>
            우측의 <b>공고번호</b>를 드래그 복사(Ctrl+C)하신 후, <b>[D2B이동]</b>을 눌러 메인 검색창에 붙여넣기(Ctrl+V)하시면 바로 확인 가능합니다.
        </div>
        
        {bid_html}
        
        <br>
        <hr style='border: 0; border-top: 1px solid #eee;'>
        <p style='font-size:11px; color:gray;'>본 메일은 Dabeeo 스크리닝 알고리즘에 의해 자동 분석 및 발송되었습니다.</p>
    </body>
    </html>
    """
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_list, msg.as_string())
        print(f"✅ 맞춤형 브리핑 발송 완료! 수신처: {receiver_list}")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

if __name__ == "__main__":
    api_key = os.environ.get("DATA_GO_KR_API_KEY")
    bids_data = get_defense_bids(api_key)
    send_email(bids_data)
