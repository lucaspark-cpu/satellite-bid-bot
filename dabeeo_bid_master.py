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
# 1. 시스템 통합 글로벌 설정
# ==========================================
# 수신자 이메일 명단 일원화 (To 창에 한 번에 노출되어 동시 발송됨)
RECEIVERS = ['lucas.park@dabeeo.com', 'joohyeon.kim@dabeeo.com']

# 공공데이터포털 API 서비스 키 설정
SERVICE_KEY = '+emmedaZrwpwK2FqtKT9BiUA9/qWfUYkm3pFh/w95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg=='

# 발송용 Gmail 계정 설정 (환경변수 기본값 연동)
SENDER_EMAIL = os.environ.get("SMTP_EMAIL", "lucas.park@dabeeo.com")
SENDER_PASSWORD = os.environ.get("SMTP_PASSWORD", "yxphvbqxpucobyut")

# API 엔드포인트 정의
G2B_ENDPOINTS = {
    '용역': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch',
    '물품': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThngPPSSrch'
}
D2B_ENDPOINTS = {
    '경쟁입찰': 'https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcCmpetBidPblancList',
    '공개수의': 'https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcOthbcVltrnNtatPlanList'
}

KEYWORDS = ['위성', '영상', '공간정보']

# 기존 다비오 필터링 키워드 스펙 유지
NEGATIVE_KEYWORDS = ["제조설비", "공장생산", "공장등록", "단순제조", "탑재체", "부품", "수리", "정비", "기체", "배터리", "하드웨어", "조경", "폐기물", "청소", "구매"]
HIGH_WEIGHT_KEYWORDS = ["영상", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제"]
MID_WEIGHT_KEYWORDS = ["위성", "드론", "무인기", "정찰", "감시", "시스템", "활용방안", "연구", "정보", "구축"]

# ==========================================
# 2. 다비오 스코어링 알고리즘 (기존 버전 유지)
# ==========================================
def evaluate_bid(title):
    for nk in NEGATIVE_KEYWORDS:
        if nk in title.replace(" ", ""):
            return -1, "제외"

    score = 0
    for hk in HIGH_WEIGHT_KEYWORDS:
        if hk in title:
            score += 30
    for mk in MID_WEIGHT_KEYWORDS:
        if mk in title:
            score += 15

    if score >= 50:
        return score, "상 (핵심 타겟) 🎯"
    elif score >= 20:
        return score, "중 (검토 권장) 🔍"
    else:
        return score, "하 (단순 키워드) 💡"

# ==========================================
# 3. 데이터 수집 및 융합 마스터 엔진
# ==========================================
def collect_and_fuse_bids():
    # 한국 표준시(KST) 기준 날짜 계산 파이프라인
    kst_now = datetime.utcnow() + timedelta(hours=9)
    seven_days_ago = kst_now - timedelta(days=7)
    
    g2b_start = seven_days_ago.strftime('%Y%m%d0000')
    g2b_end = kst_now.strftime('%Y%m%d2359')

    master_container = {
        "상 (핵심 타겟) 🎯": {},
        "중 (검토 권장) 🔍": {},
        "하 (단순 키워드) 💡": {}
    }

    # 💡 [NameError 해결] 변수 스코프를 최상단에 명확히 정의
    keyword_str = ", ".join(KEYWORDS)

    for keyword in KEYWORDS:
        # Part A: 나라장터(G2B) 수집
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
                        
                        score, grade = evaluate_bid(title)
                        if score != -1:
                            item['_api_type'] = api_tag
                            item['formatted_url'] = item.get('bidNtceUrl', 'https://www.g2b.go.kr/')
                            item['display_org'] = item.get('dminsttNm', '-')
                            item['display_date'] = item.get('bidClseDt', '-')
                            master_container[grade][notice_no] = item
            except Exception:
                continue

        # Part B: 국방전자조달(D2B) 수집
        keyword_encoded = urllib.parse.quote(keyword)
        for api_tag, url in D2B_ENDPOINTS.items():
            full_url = f"{url}?serviceKey={SERVICE_KEY}&pageNo=1&numOfRows=100&bidNm={keyword_encoded}"
            try:
                res = requests.get(full_url, timeout=15)
                if res.status_code == 200:
                    root = ET.fromstring(res.content)
                    for item in root.findall('.//item'):
                        title = item.findtext('bidNm', '')
                        g2b_no = item.findtext('g2bPblancNo', '').strip()
                        clse_dt_str = item.findtext('rgstClseDt', '')
                        
                        # KST 기준 마감 대조 필터링 및 시차 보정
                        if clse_dt_str and len(clse_dt_str) >= 12:
                            try:
                                clse_dt = datetime.strptime(clse_dt_str[:12], "%Y%m%d%H%M")
                                if kst_now > clse_dt: continue
                                formatted_clse = f"{clse_dt_str[0:4]}-{clse_dt_str[4:6]}-{clse_dt_str[6:8]} {clse_dt_str[8:10]}:{clse_dt_str[10:12]}"
                            except Exception:
                                formatted_clse = clse_dt_str
                        else:
                            formatted_clse = clse_dt_str if clse_dt_str else "-"

                        score, grade = evaluate_bid(title)
                        if score != -1:
                            bid_id = g2b_no if g2b_no else title
                            master_container[grade][bid_id] = {
                                'bidNtceNm': title,
                                'display_org': item.findtext('ornt', '-'),
                                '_api_type': f"D2B {api_tag}",
                                'formatted_url': 'https://www.d2b.go.kr/',
                                'display_date': formatted_clse,
                                'bidNtceNo': g2b_no if g2b_no else "공고서참조",
                                'prtcptLmtRgnNm': "국방특과",
                                'indstrytyLmtYn': "N"
                            }
            except Exception:
                continue

    return master_container, keyword_str

# ==========================================
# 4. HTML 리포트 UI 빌드 및 동시 발송 엔진
# ==========================================
def build_html_and_dispatch():
    container, keyword_str = collect_and_fuse_bids()
    total_count = sum(len(bids) for bids in container.values())
    
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
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 수요기관:</b> {item.get('display_org', '-')}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 지역제한:</b> <span style='color:#27ae60; font-weight:bold;'>{region}</span> | <b>업종제한:</b> {industry_lmt}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 공고일시:</b> {item.get('bidNtceDt', '-')} | <b>마감일시:</b> <span style='color: #e74c3c; font-weight:bold;'>{item.get('display_date', '-')}</span></p>
                    <p style='margin: 8px 0 0 0;'><a href='{item.get('formatted_url', '-')}' target='_blank' style='background-color: {border_color}; color: white; padding: 4px 8px; text-decoration: none; border-radius: 3px; font-size:12px;'>공고 상세 보기</a></p>
                </div>
                """
        html_content += "</body></html>"
    else:
        html_content = f"<h3>최근 일주일 내에 등록된 '{keyword_str}' 관련 유효 물품/용역 공고가 없습니다.</h3>"

    # 이메일 전송 (To 헤더에 연동하여 단일 동시 발송)
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
        print(f"✅ 통합 알림 동시 발송 완료! 대상자: {RECEIVERS}")
    except Exception as e:
        print(f"❌ 통합 알림 발송 실패: {e}", file=sys.stderr)

if __name__ == "__main__":
    build_html_and_dispatch()
