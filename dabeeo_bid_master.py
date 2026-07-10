import os
import sys
import requests
import urllib.parse
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET

# ==========================================
# 1. 시스템 통합 글로벌 설정 (이메일 작성법 일원화)
# ==========================================
# To 헤더 창에 수신처 리스트가 한 번에 깔끔하게 노출되어 발송되는 동시 발송 구조
RECEIVERS = ['lucas.park@dabeeo.com', 'joohyeon.kim@dabeeo.com']

# 공공데이터포털 API 서비스 키 설정
SERVICE_KEY = '+emmedaZrwpwK2FqtKT9BiUA9/qWfUYkm3pFh/w95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg=='

# 발송용 Gmail 계정 설정 (환경변수 또는 하드코딩 백업 연동)
SENDER_EMAIL = os.environ.get("SMTP_EMAIL", "lucas.park@dabeeo.com")
SENDER_PASSWORD = os.environ.get("SMTP_PASSWORD", "yxphvbqxpucobyut")

# API 엔드포인트 파이프라인 아키텍처 정의
G2B_ENDPOINTS = {
    '용역': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch',
    '물품': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThngPPSSrch'
}
D2B_ENDPOINTS = {
    '경쟁입찰': 'https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcCmpetBidPblancList',
    '공개수의': 'https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcOthbcVltrnNtatPlanList'
}

KEYWORDS = ['위성', '영상', '공간정보']

# ==========================================
# 2. 다비오 스코어링 & 노이즈 정제 알고리즘
# ==========================================
# 원천 배제할 네거티브 키워드 (요청 반영)
NEGATIVE_KEYWORDS = [
    "장치", "기념", "콘텐츠", "콘텐츠", "설치", "문화", "의료", "홍보", "방송", "초음파", 
    "여행", "시설", "의학", "드라마", "스포츠", "자막", "행사", "제조설비", "공장생산", 
    "공장등록", "단순제조", "탑재체", "부품", "수리", "정비", "기체", "배터리", "하드웨어", 
    "청소", "폐기물", "구매", "물품구매", "구입"
]

# 무인수상선/해양위성 검보정 공고를 무조건 상으로 올리기 위한 가중치 세팅
HIGH_WEIGHT_KEYWORDS = ["영상", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제", "무인", "관측", "해양", "검보정"]
MID_WEIGHT_KEYWORDS = ["위성", "드론", "무인기", "정찰", "감시", "시스템", "활용방안", "연구", "정보", "구축"]

def evaluate_bid_grade(title):
    # 1. 정밀 네거티브 스크리닝 (원본 텍스트 및 공백 제거 텍스트 교차 검증)
    for nk in NEGATIVE_KEYWORDS:
        if nk in title or nk in title.replace(" ", ""):
            return -1, "제외"

    score = 0
    # 2. 하이/미드 가중치 기반 가치 점수 연산
    for hk in HIGH_WEIGHT_KEYWORDS:
        if hk in title:
            score += 30
    for mk in MID_WEIGHT_KEYWORDS:
        if mk in title:
            score += 15

    # 3. 최종 연관 등급 분기
    if score >= 50:
        return score, "상 (핵심 타겟) 🎯"
    elif score >= 20:
        return score, "중 (검토 권장) 🔍"
    else:
        return score, "하 (단순 키워드) 💡"

# ==========================================
# 3. 데이터 융합 및 실시간 동시 수집 엔진
# ==========================================
def collect_and_fuse_bids():
    # KST 기준 시간 동기화 파이프라인
    kst_now = datetime.utcnow() + timedelta(hours=9)
    seven_days_ago = kst_now - timedelta(days=7)
    
    g2b_start = seven_days_ago.strftime('%Y%m%d0000')
    g2b_end = kst_now.strftime('%Y%m%d2359')

    master_container = {
        "상 (핵심 타겟) 🎯": {},
        "중 (검토 권장) 🔍": {},
        "하 (단순 키워드) 💡": {}
    }

    keyword_str = ", ".join(KEYWORDS)

    for keyword in KEYWORDS:
        # Part A: 나라장터(G2B) 데이터 수집 및 안전 분기
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
                            item['_api_type'] = api_tag
                            item['formatted_url'] = item.get('bidNtceUrl', 'https://www.g2b.go.kr/')
                            item['display_org'] = item.get('dminsttNm', '-')
                            item['display_date'] = item.get('bidClseDt', '-')
                            master_container[grade][notice_no] = item
            except Exception:
                continue

        # Part B: 국방전자조달(D2B) 수집 엔진 (XML 누락 오류 완벽 해결)
        keyword_encoded = urllib.parse.quote(keyword)
        for api_tag, url in D2B_ENDPOINTS.items():
            full_url = f"{url}?serviceKey={SERVICE_KEY}&pageNo=1&numOfRows=100&bidNm={keyword_encoded}"
            try:
                res = requests.get(full_url, timeout=15)
                if res.status_code == 200:
                    root = ET.fromstring(res.content)
                    # D2B 명세서 계층 경로 구조 매칭으로 누락 현상 원천 차단
                    items = root.findall('.//item')
                    
                    for item in items:
                        title = item.findtext('bidNm', '')
                        g2b_no = item.findtext('g2bPblancNo', '').strip()
                        clse_dt_str = item.findtext('rgstClseDt', '') # 마감 일시 파싱
                        
                        # KST 실시간 타임 스탬프 필터링
                        if clse_dt_str and len(clse_dt_str) >= 12:
                            try:
                                clse_dt = datetime.strptime(clse_dt_str[:12], "%Y%m%d%H%M")
                                if kst_now > clse_dt: continue
                                formatted_clse = f"{clse_dt_str[0:4]}-{clse_dt_str[4:6]}-{clse_dt_str[6:8]} {clse_dt_str[8:10]}:{clse_dt_str[10:12]}"
                            except Exception:
                                formatted_clse = clse_dt_str
                        else:
                            formatted_clse = clse_dt_str if clse_dt_str else "-"

                        score, grade = evaluate_bid_grade(title)
                        if score != -1:
                            bid_id = g2b_no if g2b_no else title
                            master_container[grade][bid_id] = {
                                'bidNtceNm': title,
                                'display_org': item.findtext('ornt', '-'),
                                '_api_type': f"D2B {api_tag}",
                                'formatted_url': 'https://www.d2b.go.kr/',
                                'display_date': formatted_clse,
                                'bidNtceNo': g2b_no if g2b_no else "공고서참조",
                                'prtcptLmtRgnNm': "국방전용",
                                'indstrytyLmtYn': "N"
                            }
            except Exception:
                continue

    return master_container, keyword_str

# ==========================================
# 4. 통합 리포트 UI 빌드 및 발송
# ==========================================
def build_html_and_dispatch():
    container, keyword_str = collect_and_fuse_bids()
    total_count = sum(len(bids) for bids in container.values())
    
    subject = "📢 [나라장터/D2B 통합] 다비오 맞춤형 신규 용역/물품 공고 리포트"
    
    if total_count > 0:
        html_content = f"""
        <html>
        <body style='font-family: Arial, sans-serif; line-height: 1.6; color: #333;'>
            <h2>🚀 다비오 맞춤형 입찰공고 리포트 (G2B + D2B 융합형)</h2>
            <p>다비오 핵심 비즈니스 연관도 필터링 알고리즘에 의해 자동 정제 및 분류된 결과 리포트입니다.</p>
            <p style='font-size:12px; color:gray;'>모니터링 타겟 키워드: {keyword_str}</p>
        """
        
        for grade in ["상 (핵심 타겟) 🎯", "중 (검토 권장) 🔍", "하 (단순 키워드) 💡"]:
            items_dict = container[grade]
            if not items_dict: continue
                
            sorted_items = sorted(items_dict.values(), key=lambda x: x.get('bidNtceDt', ''), reverse=True)
            border_color = "#e74c3c" if "상" in grade else "#f39c12" if "중" in grade else "#3498db"
            html_content += f"<h3 style='color:{border_color}; margin-top:30px; border-bottom:2px solid {border_color}; padding-bottom:5px;'>{grade} ({len(sorted_items)}건)</h3>"
            
            for idx, item in enumerate(sorted_items, 1):
                region = item.get('prtcptLmtRgnNm') or item.get('cnstrtsiteRgnNm') or "전국"
                industry_lmt = "있음" if item.get('indstrytyLmtYn') == 'Y' else "없음"
                api_tag = item.get('_api_type', '용역')

                html_content += f"""
                <div style='margin-bottom: 15px; padding: 12px; border-left: 4px solid {border_color}; background-color: #f9f9f9;'>
                    <h4 style='margin: 0 0 8px 0; color: #2c3e50;'>
                        <span style='background-color:{border_color}; color:white; padding:2px 6px; font-size:11px; border-radius:3px; margin-right:5px;'>{api_tag}</span>
                        {idx}. {item.get('bidNtceNm', '공고명 없음')}
                    </h4>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 수요/발주기관:</b> {item.get('display_org', '-')}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 지역제한:</b> <span style='color:#27ae60; font-weight:bold;'>{region}</span> | <b>업종제한:</b> {industry_lmt}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 마감일시:</b> <span style='color: #e74c3c; font-weight:bold;'>{item.get('display_date', '-')}</span></p>
                    <p style='margin: 8px 0 0 0;'><a href='{item.get('formatted_url', '-')}' target='_blank' style='background-color: {border_color}; color: white; padding: 4px 8px; text-decoration: none; border-radius: 3px; font-size:12px; font-weight:bold;'>공고 상세 보기</a></p>
                </div>
                """
        html_content += "</body></html>"
    else:
        html_content = f"<h3>진행 중인 '{keyword_str}' 관련 유효 물품/용역 공고가 없습니다.</h3>"

    # 이메일 일괄 동시 발송 트랜잭션 수행
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = ", ".join(RECEIVERS)
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVERS, msg.as_string())
        print(f"✅ [통합 완결] 동시 전송 성공 -> {RECEIVERS}")
    except Exception as e:
        print(f"❌ 전송 실패: {e}", file=sys.stderr)

if __name__ == "__main__":
    build_html_and_dispatch()
