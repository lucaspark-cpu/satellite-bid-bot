import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

# ==========================================
# 1. 시스템 기본 설정 및 이메일 정보
# ==========================================
SENDER_EMAIL = 'lucas.park@dabeeo.com'
SENDER_PASSWORD = 'yxphvbqxpucobyut' 

# 수신자 리스트 (독립 개별 발송 대상)
RECEIVER_LIST = [
    'lucas.park@dabeeo.com',
    'joohyeon.kim@dabeeo.com'
]

SERVICE_KEY = '+emmedaZrwpwK2FqtKT9BiUA9/qWfUYkm3pFh/w95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg=='

# 12번(용역), 14번(물품) 엔드포인트 정의
API_ENDPOINTS = {
    '용역': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch',
    '물품': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThngPPSSrch'
}

KEYWORDS = ['위성', '영상', '분석', '공간정보']

# 다비오 맞춤형 필터링 키워드 셋팅 (제조/설비/생산 원천 배제)
NEGATIVE_KEYWORDS = ["제조설비", "공장생산", "공장등록", "단순제조", "탑재체", "부품", "수리", "정비", "기체", "배터리", "하드웨어", "조경", "폐기물", "청소", "구매"]
HIGH_WEIGHT_KEYWORDS = ["영상", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제"]
MID_WEIGHT_KEYWORDS = ["위성", "드론", "무인기", "정찰", "감시", "시스템", "활용방안", "연구", "정보", "구축"]

# ==========================================
# 2. 다비오 연관도 스코어링 알고리즘
# ==========================================
def evaluate_bid(title):
    # 1. 네거티브 필터링 (제조, 설비, 하드웨어 배제)
    for nk in NEGATIVE_KEYWORDS:
        if nk in title.replace(" ", ""):  # 띄어쓰기 공백 제거 후 검사
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
# 3. 독립형 개별 발송 로직 (Loop)
# ==========================================
def send_individual_emails(subject, content):
    """
    RECEIVER_LIST의 수신자들에게 각각 독립된 메일 객체로 개별 발송합니다.
    """
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            
            for receiver in RECEIVER_LIST:
                msg = MIMEMultipart()
                msg['From'] = SENDER_EMAIL
                msg['To'] = receiver  # 받는 사람 창에 본인 주소만 깔끔하게 노출
                msg['Subject'] = subject
                msg.attach(MIMEText(content, 'html', 'utf-8'))
                
                server.sendmail(SENDER_EMAIL, [receiver], msg.as_string())
                print(f"   -> [발송 완료] 수신처: {receiver}")
                
        print("✅ 모든 수신자에게 개별 발송을 성공적으로 마쳤습니다.")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

# ==========================================
# 4. 데이터 수집 및 융합 마스터 로직
# ==========================================
def main():
    # 최근 7일치 기간 계산
    today = datetime.now()
    seven_days_ago = today - timedelta(days=7)
    inqry_bgn_dt = seven_days_ago.strftime('%Y%m%d0000')
    inqry_end_dt = today.strftime('%Y%m%d2359')

    # 등급별 중복 제거 보장 딕셔너리 구조
    categorized_bids = {
        "상 (핵심 타겟) 🎯": {},
        "중 (검토 권장) 🔍": {},
        "하 (단순 키워드) 💡": {}
    }

    # 키워드 ➡️ 입찰구분(용역/물품) 순회하며 데이터 융합
    for keyword in KEYWORDS:
        for api_type, api_url in API_ENDPOINTS.items():
            params = {
                'ServiceKey': SERVICE_KEY,
                'type': 'json',               
                'numOfRows': '50',            
                'pageNo': '1',                
                'inqryDiv': '1', # 1: 공고게시일시 기준              
                'inqryBgnDt': inqry_bgn_dt,   
                'inqryEndDt': inqry_end_dt,   
                'bidNtceNm': keyword,         
                'bidClseExcpYn': 'Y'          
            }
            
            try:
                response = requests.get(api_url, params=params, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    items = data['response']['body']['items']
                    
                    if isinstance(items, dict):
                        items = [items]
                        
                    for item in items:
                        notice_no = item.get('bidNtceNo')
                        title = item.get('bidNtceNm', '공고명 없음')
                        
                        if notice_no:
                            # 알고리즘 평가 실행
                            score, grade = evaluate_bid(title)
                            if score != -1: # 네거티브 필터링 통과한 경우만 기록
                                # 업무구분(용역/물품) 태그 강제 주입
                                item['_api_type'] = api_type 
                                categorized_bids[grade][notice_no] = item
            except Exception:
                continue

    # ==========================================
    # 5. HTML 리포트 빌드
    # ==========================================
    total_count = sum(len(bids) for bids in categorized_bids.values())
    keyword_str = ", ".join(KEYWORDS)
    subject = "📢 [나라장터] 다비오 맞춤형 신규 용역/물품 공고 리포트"

    if total_count > 0:
        html_content = f"""
        <html>
        <body style='font-family: Arial, sans-serif; line-height: 1.6; color: #333;'>
            <h2>🚀 나라장터 맞춤형 인텔리전스 (최근 7일)</h2>
            <p>제조·설비 공고는 자동 제외됐으며, 다비오 도메인 연관도에 따라 총 <b>{total_count}건</b>의 유효 공고가 분류되었습니다.</p>
            <p style='font-size:12px; color:gray;'>조회 키워드: {keyword_str}</p>
        """
        
        for grade in ["상 (핵심 타겟) 🎯", "중 (검토 권장) 🔍", "하 (단순 키워드) 💡"]:
            items_dict = categorized_bids[grade]
            if not items_dict:
                continue
                
            # 등급별 정렬 (최신 공고순)
            sorted_items = sorted(items_dict.values(), key=lambda x: x.get('bidNtceDt', ''), reverse=True)
            
            border_color = "#e74c3c" if "상" in grade else "#f39c12" if "중" in grade else "#3498db"
            html_content += f"<h3 style='color:{border_color}; margin-top:30px; border-bottom:2px solid {border_color}; padding-bottom:5px;'>{grade} ({len(sorted_items)}건)</h3>"
            
            for idx, item in enumerate(sorted_items, 1):
                # 업종제한 및 지역제한 정보 파싱 후 가독성 보완
                region = item.get('prtcptLmtRgnNm') or item.get('cnstrtsiteRgnNm') or "전국"
                industry_lmt = "있음" if item.get('indstrytyLmtYn') == 'Y' else "없음"
                api_tag = item.get('_api_type', '용역')

                html_content += f"""
                <div style='margin-bottom: 15px; padding: 12px; border-left: 4px solid {border_color}; background-color: #f9f9f9;'>
                    <h4 style='margin: 0 0 8px 0; color: #2c3e50;'>
                        <span style='background-color:{border_color}; color:white; padding:2px 6px; font-size:11px; border-radius:3px; margin-right:5px;'>{api_tag}</span>
                        {idx}. {item.get('bidNtceNm', '공고명 없음')}
                    </h4>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 수요기관:</b> {item.get('dminsttNm', '-')}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 지역제한:</b> <span style='color:#27ae60; font-weight:bold;'>{region}</span> | <b>업종제한:</b> {industry_lmt}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 공고일시:</b> {item.get('bidNtceDt', '-')} | <b>마감일시:</b> <span style='color: #e74c3c; font-weight:bold;'>{item.get('bidClseDt', '-')}</span></p>
                    <p style='margin: 8px 0 0 0;'><a href='{item.get('bidNtceUrl', '-')}' target='_blank' style='background-color: {border_color}; color: white; padding: 4px 8px; text-decoration: none; border-radius: 3px; font-size:12px;'>공고 상세 보기</a></p>
                </div>
                """
        html_content += "</body></html>"
    else:
        html_content = f"<h3>최근 일주일 내에 등록된 '{keyword_str}' 관련 유효 물품/용역 공고가 없습니다.</h3>"

    # 최종 발송 실행 (수신자별 루프 기동)
    send_individual_emails(subject, html_content)

if __name__ == "__main__":
    main()
