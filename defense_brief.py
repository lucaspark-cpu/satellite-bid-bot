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
NEGATIVE_KEYWORDS = ["제조설비", "공장생산", "공장등록", "단순제조", "탑재체", "부품", "수리", "정비", "기체", "배터리", "하드웨어", "발사체", "엔진", "단말기", "케이블", "안테나", "청소", "폐기물"]
HIGH_WEIGHT_KEYWORDS = ["영상", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제", "연구"]
MID_WEIGHT_KEYWORDS = ["위성", "드론", "무인기", "정찰", "감시", "시스템", "활용방안", "정보", "구축"]

def evaluate_bid(title):
    # 1. 네거티브 필터링 (제조/설비/정비 배제)
    for nk in NEGATIVE_KEYWORDS:
        if nk in title.replace(" ", ""):
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
# 2. 독립형 개별 발송 로직 (Loop)
# ==========================================
def send_individual_emails(subject, content):
    receiver_list = ["lucas.park@dabeeo.com", "joohyeon.kim@dabeeo.com"]
    sender_email = os.environ.get("SMTP_EMAIL", "lucas.park@dabeeo.com")
    sender_password = os.environ.get("SMTP_PASSWORD")
    
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            
            for receiver in receiver_list:
                msg = MIMEMultipart()
                msg['From'] = sender_email
                msg['To'] = receiver  # 수신자창 독점 노출
                msg['Subject'] = subject
                msg.attach(MIMEText(content, 'html', 'utf-8'))
                
                server.sendmail(sender_email, [receiver], msg.as_string())
                print(f"   -> [D2B 발송 완료] 수신처: {receiver}")
                
        print("✅ 모든 수신자에게 D2B 개별 발송을 완료했습니다.")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

# ==========================================
# 3. D2B 데이터 수집 (공고게시일시 기준 + 최근 1개월)
# ==========================================
def get_defense_bids(service_key):
    # 최근 1개월(30일) 기간 설정
    end_date = datetime.now().strftime("%Y%m%d")
    begin_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
    search_keywords = ["위성", "영상", "드론", "AI", "공간정보"]
    raw_bids = {}

    for keyword in search_keywords:
        keyword_encoded = urllib.parse.quote(keyword)
        
        # 💡 [교정] 엔드포인트를 개찰일 기준이 아닌 '공고게시일시 기준 검색(getBidPblancList)'으로 매칭
        # 공사 항목 노이즈를 필터링하기 위해 넉넉하게 100건 수집 후 내부 가공
        url = (
            f"https://apis.data.go.kr/1690000/BidPblancInfoService/getBidPblancList" 
            f"?serviceKey={service_key}"
            f"&pageNo=1"
            f"&numOfRows=100"
            f"&bidPblancBgnDate={begin_date}"  # 💡 공고게시 시작일자
            f"&bidPblancEndDate={end_date}"    # 💡 공고게시 종료일자
            f"&bidNm={keyword_encoded}"
        )
        
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                items = root.findall('.//item')
                
                for item in items:
                    bid_nm = item.findtext('bidNm', 'N/A')
                    g2b_no = item.findtext('g2bPblancNo', '').strip()
                    ornt = item.findtext('ornt', 'N/A')
                    cntrct_mth = item.findtext('cntrctMth', 'N/A')
                    openg_dt = item.findtext('opengDt', 'N/A')
                    
                    # 💡 [필터링] 공사(Construction) 업종이 공고명이나 계약방식에 들어가 있으면 원천 배제
                    if "공사" in bid_nm or "공사" in cntrct_mth:
                        continue
                        
                    bid_id = g2b_no if g2b_no else bid_nm
                    
                    if bid_id not in raw_bids:
                        raw_bids[bid_id] = {
                            'bidNm': bid_nm,
                            'ornt': ornt,
                            'cntrctMth': cntrct_mth,
                            'opengDt': openg_dt,
                            'g2bPblancNo': g2b_no
                        }
        except Exception as e:
            print(f"D2B API 오류 ({keyword}): {e}")

    # ==========================================
    # 4. 알고리즘 스크리닝 및 결과 통합
    # ==========================================
    categorized_bids = {"상 (핵심 타겟) 🎯": [], "중 (검토 권장) 🔍": [], "하 (단순 키워드) 💡": []}
    
    for bid_id, data in raw_bids.items():
        score, grade = evaluate_bid(data['bidNm'])
        if score != -1:
            categorized_bids[grade].append(data)

    return generate_html_report(categorized_bids)

def generate_html_report(categorized_bids):
    total_valid = sum(len(bids) for bids in categorized_bids.values())
    if total_valid == 0:
        return "<p>최근 1개월간 D2B 시스템에 등록된 다비오 맞춤형 유효 공고가 없습니다.</p>"

    html = ""
    for grade in ["상 (핵심 타겟) 🎯", "중 (검토 권장) 🔍", "하 (단순 키워드) 💡"]:
        bids = categorized_bids[grade]
        if not bids:
            continue
            
        color = "#e74c3c" if "상" in grade else "#f39c12" if "중" in grade else "#3498db"
        html += f"<h4 style='color:{color}; margin-top:25px; border-bottom:2px solid {color}; padding-bottom:5px;'>{grade} ({len(bids)}건)</h4>"
        
        for idx, item in enumerate(bids, 1):
            g2b_no = item['g2bPblancNo']
            
            html += f"""
            <div style='margin-bottom: 15px; padding: 12px; border-left: 4px solid {color}; background-color: #f9f9f9;'>
                <h4 style='margin: 0 0 8px 0; color: #2c3e50;'>{idx}. {item['bidNm']}</h4>
                <p style='margin: 4px 0; font-size:13px;'><b>🔹 발주기관:</b> {item['ornt']} | <b>계약방식:</b> {item['cntrctMth']}</p>
                <p style='margin: 4px 0; font-size:13px;'><b>🔹 검색용 공고번호:</b> <span style='color:#2c3e50; font-weight:bold;'>{g2b_no}</span></p>
                <p style='margin: 8px 0 0 0;'><a href='https://www.d2b.go.kr/' target='_blank' style='background-color: {color}; color: white; padding: 4px 8px; text-decoration: none; border-radius: 3px; font-size:12px;'>D2B 국방조달시스템 바로가기</a></p>
            </div>
            """
    return html

if __name__ == "__main__":
    api_key = os.environ.get("DATA_GO_KR_API_KEY")
    bids_data = get_defense_bids(api_key)
    send_email_content = send_individual_emails
    
    # 이메일 제목 정의 및 기동
    subject = "📢 [D2B 국방조달] 다비오 맞춤형 신규 군 소요 공고 리포트 (최근 1개월)"
    send_individual_emails(subject, bids_data)
