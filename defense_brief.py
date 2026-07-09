import os
import requests
import urllib.parse
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET

# ==========================================
# 1. 다비오(Dabeeo) 맞춤형 알고리즘 및 필터 세팅
# ==========================================
NEGATIVE_KEYWORDS = ["제조설비", "공장생산", "공장등록", "단순제조", "탑재체", "부품", "수리", "정비", "기체", "배터리", "하드웨어", "발사체", "엔진", "단말기", "케이블", "안테나", "청소", "폐기물"]
HIGH_WEIGHT_KEYWORDS = ["위성", "상용위성", "영상", "영상정보", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제", "연구", "활용방안"]
MID_WEIGHT_KEYWORDS = ["드론", "무인기", "정찰", "감시", "시스템", "정보", "구축"]

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
# 2. 수신자별 독립형 개별 발송 로직
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
                msg['To'] = receiver  
                msg['Subject'] = subject
                msg.attach(MIMEText(content, 'html', 'utf-8'))
                
                server.sendmail(sender_email, [receiver], msg.as_string())
                print(f"   -> [D2B 발송 성공] 수신처: {receiver}")
                
        print("✅ 모든 수신자에게 D2B 개별 통지를 완료했습니다.")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

# ==========================================
# 3. D2B 공식 API 동시 구동 (경쟁입찰 + 공개수의협상)
# ==========================================
def get_defense_bids(service_key):
    # 명세서 기반 유효 오퍼레이션 엔드포인트 정의 (시설 공사 원천 배제)
    endpoints = [
        "getDmstcCmpetBidPblancList",      # 1. 국내 경쟁입찰공고 목록
        "getDmstcOthbcVltrnNtatPlanList"   # 2. 국내 공개수의협상계획 목록 (★ 수의계약 누락 방지 핵심)
    ]
    
    search_keywords = ["위성", "영상", "드론", "AI", "공간정보", "활용방안"]
    raw_bids = {}
    current_time = datetime.now()

    for keyword in search_keywords:
        keyword_encoded = urllib.parse.quote(keyword)
        
        for operation in endpoints:
            url = (
                f"https://apis.data.go.kr/1690000/BidPblancInfoService/{operation}" 
                f"?serviceKey={service_key}"
                f"&pageNo=1"
                f"&numOfRows=100"
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
                        cntrct_mth = item.findtext('cntrctMth', 'N/A')
                        
                        # 💡 [마감 필터링] 마감일시 데이터를 읽어와서 현재 시간 지나갔으면 탈락시킴
                        clse_dt_str = item.findtext('rgstClseDt') # 입찰참가등록 마감일시
                        if clse_dt_str and len(clse_dt_str) >= 12:
                            try:
                                clse_dt = datetime.strptime(clse_dt_str[:12], "%Y%m%d%H%M")
                                if current_time > clse_dt:
                                    continue # 마감된 공고는 가차 없이 패스
                            except Exception:
                                pass
                        
                        # 고유 식별값 지정
                        bid_id = g2b_no if g2b_no else bid_nm
                        
                        if bid_id not in raw_bids:
                            # 경쟁입찰과 수의협상 UI 태그 분화
                            source_tag = "공개수의" if "OthbcVltrn" in operation else "경쟁입찰"
                            raw_bids[bid_id] = {
                                'bidNm': bid_nm,
                                'ornt': item.findtext('ornt', 'N/A'),
                                'cntrctMth': cntrct_mth,
                                'g2bPblancNo': g2b_no,
                                'source_tag': source_tag,
                                'clseDt': clse_dt_str
                            }
            except Exception as e:
                print(f"D2B API 융합 에러 [{operation}]: {e}")

    # ==========================================
    # 4. 알고리즘 분류 엔진 기동
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
        return "<p>현재 D2B 시스템에 등록된 진행 중인(미마감) 유효 공고가 없습니다.</p>"

    html = ""
    for grade in ["상 (핵심 타겟) 🎯", "중 (검토 권장) 🔍", "하 (단순 키워드) 💡"]:
        bids = categorized_bids[grade]
        if not bids:
            continue
            
        color = "#e74c3c" if "상" in grade else "#f39c12" if "중" in grade else "#3498db"
        html += f"<h4 style='color:{color}; margin-top:25px; border-bottom:2px solid {color}; padding-bottom:5px;'>{grade} ({len(bids)}건)</h4>"
        
        for idx, item in enumerate(bids, 1):
            g2b_no = item['g2bPblancNo']
            clse_str = item['clseDt']
            
            # 마감 일시 가독성 변환 (YYYY-MM-DD HH:MM)
            if clse_str and len(clse_str) >= 12:
                formatted_clse = f"{clse_str[0:4]}-{clse_str[4:6]}-{clse_str[6:8]} {clse_str[8:10]}:{clse_str[10:12]}"
            else:
                formatted_clse = clse_str
                
            html += f"""
            <div style='margin-bottom: 15px; padding: 12px; border-left: 4px solid {color}; background-color: #f9f9f9;'>
                <h4 style='margin: 0 0 8px 0; color: #2c3e50;'>
                    <span style='background-color:#7f8c8d; color:white; padding:1px 5px; font-size:11px; border-radius:3px; vertical-align:middle;'>{item['source_tag']}</span>
                    {item['bidNm']}
                </h4>
                <p style='margin: 4px 0; font-size:13px;'><b>🔹 발주기관:</b> {item['ornt']} | <b>계약방식:</b> {item['cntrctMth']}</p>
                <p style='margin: 4px 0; font-size:13px;'><b>🔹 등록마감일시:</b> <span style='color:#e74c3c; font-weight:bold;'>{formatted_clse}</span></p>
                <p style='margin: 4px 0; font-size:13px;'><b>🔹 검색용 공고번호:</b> <b>{g2b_no}</b></p>
                <p style='margin: 8px 0 0 0;'><a href='https://www.d2b.go.kr/' target='_blank' style='background-color: {color}; color: white; padding: 4px 8px; text-decoration: none; border-radius: 3px; font-size:12px;'>D2B 시스템에서 검색하기</a></p>
            </div>
            """
    return html

if __name__ == "__main__":
    api_key = os.environ.get("DATA_GO_KR_API_KEY")
    bids_data = get_defense_bids(api_key)
    
    subject = "🛡️ [D2B 최종본] 다비오 맞춤형 미마감 국방 입찰공고 인텔리전스"
    send_individual_emails(subject, bids_data)
