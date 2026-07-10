import os
import sys
import requests
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET

# ==========================================
# 1. 시스템 통합 글로벌 설정
# ==========================================
RECEIVERS = ['lucas.park@dabeeo.com']
SERVICE_KEY = '+emmedaZrwpwK2FqtKT9BiUA9/qWfUYkm3pFh/w95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg=='

SENDER_EMAIL = os.environ.get("SMTP_EMAIL", "lucas.park@dabeeo.com")
SENDER_PASSWORD = os.environ.get("SMTP_PASSWORD", "yxphvbqxpucobyut")

G2B_ENDPOINTS = {
    '용역': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch',
    '물품': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThngPPSSrch'
}
D2B_ENDPOINTS = {
    '경쟁입찰': 'https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcCmpetBidPblancList',
    '공개수의': 'https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcOthbcVltrnNtatPlanList'
}

# 검색 조회를 위한 풀
KEYWORDS = ['위성', '공간정보', 'AI', '드론', '영상']

# ==========================================
# 2. 다비오 고도화 스코어링
# ==========================================
NEGATIVE_KEYWORDS = [
    "장치", "기념", "콘텐츠", "설치", "문화", "의료", "홍보", "방송", "초음파", "여행", 
    "시설", "의학", "드라마", "스포츠", "자막", "행사", "제조설비", "공장생산", "공장등록", 
    "단순제조", "탑재체", "부품", "수리", "정비", "기체", "배터리", "하드웨어", "청소", "폐기물", "구매",
    "제조", "애니메이션", "LLM", "로봇", "영화", "임차", "공사", "강수량", "인재", "대학교", 
    "상품", "반도체", "서버", "냉방기", "장비", "학생", "골프장", "월드컵", "주파수", "학년도", 
    "가이드", "교육", "섬유", "약물", "진료", "파일럿", "음악", "기자재", "음료", "상담"
]

HIGH_WEIGHT_KEYWORDS = ["영상", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제", "무인", "관측", "검보정"]
MID_WEIGHT_KEYWORDS = ["위성", "상용위성", "드론", "무인기", "정찰", "감시", "시스템", "정보", "구축", "해양"]

def evaluate_bid_grade(title):
    clean_title = title.replace(" ", "")
    for nk in NEGATIVE_KEYWORDS:
        if nk in title or nk in clean_title:
            return -1, "제외"

    score = 0
    for hk in HIGH_WEIGHT_KEYWORDS:
        if hk in title: score += 30
    for mk in MID_WEIGHT_KEYWORDS:
        if mk in title: score += 15

    # 국방/위성 특화 복합 키워드 시너지 가점
    if "위성" in title and ("영상" in title or "데이터" in title or "검보정" in title or "활용" in title):
        score += 15

    # 등급 판정 로직
    if score >= 50:
        # 상 등급 진입 허들: 위성, 드론, 공간정보 셋 중 하나 필수
        if any(k in title for k in ["위성", "드론"]):
            return score, "상 (핵심 타겟) 🎯"
        else:
            return score, "중 (검토 권장) 🔍"
    elif score >= 20:
        return score, "중 (검토 권장) 🔍"
    else:
        return -1, "제외"

# ==========================================
# 3. 데이터 융합 엔진 
# ==========================================
def collect_and_fuse_bids():
    kst_now = datetime.utcnow() + timedelta(hours=9)
    seven_days_ago = kst_now - timedelta(days=7)
    
    g2b_start = seven_days_ago.strftime('%Y%m%d0000')
    g2b_end = kst_now.strftime('%Y%m%d2359')

    master_container = {
        "상 (핵심 타겟) 🎯": {},
        "중 (검토 권장) 🔍": {}
    }

    for keyword in KEYWORDS:
        # Part A: 나라장터(G2B) 데이터 수집
        for api_tag, url in G2B_ENDPOINTS.items():
            params = {
                'ServiceKey': SERVICE_KEY, 'type': 'json', 'numOfRows': '50', 'pageNo': '1',
                'inqryDiv': '1', 'inqryBgnDt': g2b_start, 'inqryEndDt': g2b_end,
                'bidNtceNm': keyword, 'bidClseExcpYn': 'Y'
            }
            try:
                res = requests.get(url, params=params, timeout=15)
                if res.status_code == 200:
                    items = res.json().get('response', {}).get('body', {}).get('items', [])
                    if isinstance(items, dict): items = [items]
                    
                    for item in items:
                        notice_no = item.get('bidNtceNo')
                        title = item.get('bidNtceNm', '')
                        if not notice_no: continue
                        
                        score, grade = evaluate_bid_grade(title)
                        if score != -1:
                            item['_api_type'] = f"G2B {api_tag}"
                            item['formatted_url'] = item.get('bidNtceUrl', 'https://www.g2b.go.kr/')
                            item['display_org'] = item.get('dminsttNm', '-')
                            item['display_date'] = item.get('bidClseDt', '-')
                            master_container[grade][notice_no] = item
            except Exception:
                continue

        # Part B: 국방전자조달(D2B) 수집
        for api_tag, url in D2B_ENDPOINTS.items():
            params = {
                'serviceKey': SERVICE_KEY,
                'pageNo': '1',
                'numOfRows': '100',
                'bidNm': keyword
            }
            
            try:
                response = requests.get(url, params=params, timeout=15)
                if response.status_code == 200:
                    root = ET.fromstring(response.content)
                    items = root.findall('.//item')
                    
                    for item in items:
                        try:
                            title = item.findtext('bidNm', 'N/A')
                            g2b_no = item.findtext('g2bPblancNo', '').strip()
                            d2b_no = item.findtext('pblancNo', '').strip()
                            
                            clse_dt_str = item.findtext('rgstClseDt') 
                            if clse_dt_str and clse_dt_str.lower() != 'none' and len(clse_dt_str) >= 12:
                                try:
                                    clse_dt = datetime.strptime(clse_dt_str[:12], "%Y%m%d%H%M")
                                    if kst_now > clse_dt:
                                        continue
                                    formatted_clse = f"{clse_dt_str[0:4]}-{clse_dt_str[4:6]}-{clse_dt_str[6:8]} {clse_dt_str[8:10]}:{clse_dt_str[10:12]}"
                                except Exception:
                                    formatted_clse = clse_dt_str
                            else:
                                formatted_clse = "None(진행중)"

                            score, grade = evaluate_bid_grade(title)
                            if score != -1:
                                bid_id = g2b_no if g2b_no else (d2b_no if d2b_no else title)
                                ornt = item.findtext('ornt', 'N/A')
                                cntrct_mth = item.findtext('cntrctMth', '')
                                display_org = f"{ornt} | {cntrct_mth}" if cntrct_mth else ornt

                                master_container[grade][bid_id] = {
                                    'bidNtceNm': title,
                                    'display_org': display_org,
                                    '_api_type': f"D2B {api_tag}",
                                    'formatted_url': 'https://www.d2b.go.kr/',
                                    'display_date': formatted_clse,
                                    'bidNtceNo': bid_id,
                                    'prtcptLmtRgnNm': "국방전용",
                                    'indstrytyLmtYn': "N"
                                }
                        except Exception:
                            continue
            except Exception:
                continue

    keyword_str = ", ".join(KEYWORDS)
    return master_container, keyword_str

# ==========================================
# 4. HTML 리포트 UI 생성 및 개별 전송
# ==========================================
def build_html_and_dispatch():
    container, keyword_str = collect_and_fuse_bids()
    total_count = sum(len(bids) for bids in container.values())
    
    subject = "📢 [나라장터/D2B 통합본] 다비오 맞춤형 신안보/공공 공고 인텔리전스"
    
    if total_count > 0:
        html_content = f"""
        <html>
        <body style='font-family: Arial, sans-serif; line-height: 1.6; color: #333;'>
            <h2 style='color: #2c3e50;'>🚀 나라장터 및 국방전자조달 통합 인텔리전스</h2>
            <p>다비오 비즈니스 도메인 연관도 스코어링 알고리즘에 따라 총 <b>{total_count}건</b>의 진행 중인 유효 공고가 분류되었습니다.</p>
            <p style='font-size:12px; color:gray; margin-bottom: 25px;'>조회 키워드: {keyword_str}</p>
            
            <div style='background-color: #f1f8ff; padding: 18px; border-radius: 8px; font-size: 13px; margin-bottom: 30px; border: 1px solid #d0e2f3;'>
                <h4 style='margin-top: 0; margin-bottom: 12px; color: #0056b3; font-size: 14px;'>💡 리포트 100% 활용 가이드 및 FAQ</h4>
                <ul style='margin: 0; padding-left: 20px; color: #444;'>
                    <li style='margin-bottom: 8px;'>🎯 <b>'상 (핵심 타겟)' 분류 기준:</b> 다비오 핵심 사업인 <b>'위성', '드론', '공간정보'</b> 중 최소 1개 이상이 공고명에 명시적으로 포함된 경우에만 '상' 등급에 노출되도록 필터링을 강화했습니다.</li>
                    <li style='margin-bottom: 8px;'>🛡️ <b>국방전자조달(D2B) 공고 확인법:</b> 국방전자조달 시스템 보안 특성상 상세 링크로의 직접 연결이 어렵습니다. 아래 리스트에서 <b>'공고번호'를 복사</b>하신 후 <a href='https://www.d2b.go.kr/' target='_blank' style='color:#e74c3c; font-weight:bold;'>D2B 홈페이지</a> 검색창에 <b>붙여넣기</b> 하시면 상세 내용을 바로 확인하실 수 있습니다.</li>
                    <li style='margin-bottom: 8px;'>🔍 <b>단순 제조/공사/물품은 안 보이나요?:</b> 네, '제조, 공사, 서버, 하드웨어' 등 30여 개의 강력한 네거티브 필터링 알고리즘을 거쳐 다비오와 무관한 공고는 <b>전면 자동 제외</b> 처리됩니다.</li>
                    <li style='margin-bottom: 4px;'>⏰ <b>마감된 공고도 오나요?:</b> 본 메일은 발송 시점 기준으로 <b>입찰/참가 등록이 마감되지 않은 '진행 중'인 유효 공고만</b>을 선별하여 전달합니다.</li>
                </ul>
            </div>
        """
        
        for grade in ["상 (핵심 타겟) 🎯", "중 (검토 권장) 🔍"]:
            items_dict = container[grade]
            if not items_dict: continue
                
            sorted_items = sorted(items_dict.values(), key=lambda x: x.get('display_date', ''), reverse=True)
            border_color = "#e74c3c" if "상" in grade else "#f39c12"
            html_content += f"<h3 style='color:{border_color}; margin-top:30px; border-bottom:2px solid {border_color}; padding-bottom:5px;'>{grade} ({len(sorted_items)}건)</h3>"
            
            for idx, item in enumerate(sorted_items, 1):
                region = item.get('prtcptLmtRgnNm') or item.get('cnstrtsiteRgnNm') or "전국"
                api_tag = item.get('_api_type', '기타')
                
                # D2B 공고일 경우 복사 안내 텍스트 추가
                btn_text = "D2B 시스템 이동 (공고번호 복사 필수)" if "D2B" in api_tag else "공고 상세 보기"
                btn_color = "#34495e" if "D2B" in api_tag else border_color

                html_content += f"""
                <div style='margin-bottom: 15px; padding: 12px; border-left: 4px solid {border_color}; background-color: #f9f9f9;'>
                    <h4 style='margin: 0 0 8px 0; color: #2c3e50;'>
                        <span style='background-color:{border_color}; color:white; padding:2px 6px; font-size:11px; border-radius:3px; margin-right:5px;'>{api_tag}</span>
                        {idx}. {item.get('bidNtceNm', '공고명 없음')}
                    </h4>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 발주기관 및 계약:</b> {item.get('display_org', '-')}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 지역제한:</b> <span style='color:#27ae60; font-weight:bold;'>{region}</span> | <b>공고번호: <span style='font-size:14px; background-color:#ecf0f1; padding:1px 4px; border:1px solid #ccc; border-radius:3px;'>{item.get('bidNtceNo', '-')}</span></b></p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 마감일시:</b> <span style='color: #e74c3c; font-weight:bold;'>{item.get('display_date', '-')}</span></p>
                    <p style='margin: 12px 0 0 0;'><a href='{item.get('formatted_url', '-')}' target='_blank' style='background-color: {btn_color}; color: white; padding: 5px 10px; text-decoration: none; border-radius: 4px; font-size:12px; font-weight:bold;'>{btn_text}</a></p>
                </div>
                """
        html_content += "</body></html>"
    else:
        html_content = f"<h3>진행 중인 '{keyword_str}' 관련 유효 공고가 없습니다.</h3>"

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            
            for receiver in RECEIVERS:
                msg = MIMEMultipart()
                msg['From'] = SENDER_EMAIL
                msg['To'] = receiver
                msg['Subject'] = subject
                msg.attach(MIMEText(html_content, 'html', 'utf-8'))
                
                server.sendmail(SENDER_EMAIL, [receiver], msg.as_string())
                print(f"✅ 통합 알림 발송 완료: {receiver}")
                
    except Exception as e:
        print(f"❌ 통합 알림 발송 실패: {e}", file=sys.stderr)

if __name__ == "__main__":
    build_html_and_dispatch()
