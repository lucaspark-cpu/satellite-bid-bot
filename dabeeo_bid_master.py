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

# 발송용 Gmail 계정 설정 (환경변수 없을 시 기본값 사용)
SENDER_EMAIL = os.environ.get("SMTP_EMAIL", "lucas.park@dabeeo.com")
SENDER_PASSWORD = os.environ.get("SMTP_PASSWORD", "yxphvbqxpucobyut")

# API 엔드포인트 융합 정의
G2B_ENDPOINTS = {
    '용역': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch',
    '물품': 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThngPPSSrch'
}
D2B_ENDPOINTS = {
    '경쟁입찰': 'https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcCmpetBidPblancList',
    '공개수의': 'https://apis.data.go.kr/1690000/BidPblancInfoService/getDmstcOthbcVltrnNtatPlanList'
}

KEYWORDS = ['위성', '영상', '공간정보', '디지털트윈', '드론']

# ==========================================
# 2. 고도화된 다비오 스코어링 알고리즘
# ==========================================
NEGATIVE_KEYWORDS = [
    "제조설비", "공장생산", "공장등록", "단순제조", "탑재체", "부품", "수리", "정비", "기체", 
    "배터리", "하드웨어", "발사체", "엔진", "단말기", "케이블", "안테나", "청소", "폐기물", 
    "조경", "장비구매", "물품구매", "단순구매", "서버도입", "인프라구축", "보안관제", "구입"
]
HIGH_WEIGHT_KEYWORDS = ["영상", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제"]
MID_WEIGHT_KEYWORDS = ["위성", "드론", "무인기", "정찰", "감시", "시스템", "활용방안", "연구", "정보", "구축"]

def evaluate_bid_intelligence(title):
    clean_title = title.replace(" ", "")
    
    # 1. 고도화된 네거티브 필터링 (노이즈 원천 배제)
    for nk in NEGATIVE_KEYWORDS:
        if nk in clean_title:
            return -1, "제외"

    score = 0
    # 2. 단일 키워드 가중치 산정
    for hk in HIGH_WEIGHT_KEYWORDS:
        if hk in title: score += 30
    for mk in MID_WEIGHT_KEYWORDS:
        if mk in title: score += 15

    # 3. 복합 연관도 시너지 가중치 보너스 (상/중/하 등급 변별력 고도화)
    if ("영상" in title or "공간정보" in title) and ("분석" in title or "AI" in title or "알고리즘" in title):
        score += 25  # 다비오 핵심 타겟 핵심 가중치 폭딩
    if "위성" in title and ("영상" in title or "데이터" in title):
        score += 20

    # 4. 정밀 등급 판정
    if score >= 50:
        return score, "상 (핵심 타겟) 🎯"
    elif score >= 20:
        return score, "중 (검토 권장) 🔍"
    else:
        return score, "하 (단순 키워드) 💡"

# ==========================================
# 3. 데이터 수집 및 마스터 마샬링 엔진
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

    for keyword in KEYWORDS:
        # Part A: 나라장터(G2B) 데이터 수집 및 인하우스 마샬링
        for api_tag, url in G2B_ENDPOINTS.items():
            params = {
                'ServiceKey': SERVICE_KEY, 'type': 'json', 'numOfRows': '100', 'pageNo': '1',
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
                        
                        score, grade = evaluate_bid_intelligence(title)
                        if score != -1:
                            item['_system_source'] = f"G2B {api_tag}"
                            item['formatted_url'] = item.get('bidNtceUrl', 'https://www.g2b.go.kr/')
                            item['display_org'] = item.get('dminsttNm', '-')
                            item['display_date'] = item.get('bidClseDt', '-')
                            master_container[grade][notice_no] = item
            except Exception:
                continue

        # Part B: 국방전자조달(D2B) 데이터 수집 및 실시간 시차보정 필터링
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
                        clse_dt_str = item.findtext('rgstClseDt', '') # 입찰등록 마감일시 (YYYYMMDDHHMM)
                        
                        # 💡 [핵심 버그 수정] 실시간 KST 마감 정밀 대조 필터링
                        if clse_dt_str and len(clse_dt_str) >= 12:
                            try:
                                clse_dt = datetime.strptime(clse_dt_str[:12], "%Y%m%d%H%M")
                                if kst_now > clse_dt: 
                                    continue # 마감된 방산 공고 자동 유실 차단
                                formatted_clse = f"{clse_dt_str[0:4]}-{clse_str[4:6]}-{clse_str[6:8]} {clse_str[8:10]}:{clse_str[10:12]}"
                            except Exception:
                                formatted_clse = clse_dt_str
                        else:
                            formatted_clse = clse_dt_str if clse_dt_str else "-"

                        score, grade = evaluate_bid_intelligence(title)
                        if score != -1:
                            bid_id = g2b_no if g2b_no else title
                            master_container[grade][bid_id] = {
                                'bidNtceNm': title,
                                'display_org': item.findtext('ornt', '-'),
                                '_system_source': f"D2B {api_tag}",
                                'formatted_url': 'https://www.d2b.go.kr/',
                                'display_date': formatted_clse,
                                'bidNtceNo': g2b_no if g2b_no else "공고서참조"
                            }
            except Exception:
                continue

    return master_container, keyword_str

# ==========================================
# 4. 통합 리포트 UI 빌드 및 단일 동시 발송 엔진
# ==========================================
def build_html_and_dispatch():
    container, keyword_str = collect_and_fuse_bids()
    total_count = sum(len(bids) for bids in container.values())
    
    subject = "📢 [다비오 통합] 맞춤형 신안보 및 지리공간정보 입찰공고 리포트"
    
    html_content = f"""
    <html>
    <body style='font-family: Arial, sans-serif; line-height: 1.6; color: #333;'>
        <h2 style='color: #2c3e50; border-bottom: 3px solid #2c3e50; padding-bottom: 10px;'>🚀 다비오 맞춤형 신안보 공고 리포트</h2>
        <p>조달청 나라장터(G2B) 및 국방전자조달(D2B)의 데이터를 통합 분석한 결과입니다. 단순 제조·설비 공고는 고도화 알고리즘에 의해 자동 정제되었습니다.</p>
        <p style='font-size:12px; color:gray;'>모니터링 키워드: {keyword_str}</p>
    """
    
    if total_count == 0:
        html_content += "<p style='padding:20px; background:#f8f9fa; border-radius:5px;'><b>금일 진행 중인 다비오 도메인 맞춤 유효 공고가 존재하지 않습니다.</b></p></body></html>"
    else:
        for grade in ["상 (핵심 타겟) 🎯", "중 (검토 권장) 🔍", "하 (단순 키워드) 💡"]:
            items = container[grade].values()
            if not items: continue
            
            color = "#e74c3c" if "상" in grade else "#f39c12" if "중" in grade else "#3498db"
            html_content += f"<h3 style='color:{color}; margin-top:30px; border-bottom:2px solid {color}; padding-bottom:5px;'>{grade} ({len(items)}건)</h3>"
            
            for idx, item in enumerate(items, 1):
                html_content += f"""
                <div style='margin-bottom: 15px; padding: 12px; border-left: 4px solid {color}; background-color: #f9f9f9; border-radius: 0 4px 4px 0;'>
                    <h4 style='margin: 0 0 8px 0; color: #2c3e50;'>
                        <span style='background-color:{color}; color:white; padding:2px 6px; font-size:11px; border-radius:3px; margin-right:5px;'>{item.get('_system_source')}</span>
                        {idx}. {item.get('bidNtceNm')}
                    </h4>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 수요/발주기관:</b> {item.get('display_org')} | <b>공고번호:</b> {item.get('bidNtceNo', '-')}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 마감일시:</b> <span style='color: #e74c3c; font-weight:bold;'>{item.get('display_date')}</span></p>
                    <p style='margin: 8px 0 0 0;'><a href='{item.get('formatted_url')}' target='_blank' style='background-color: {color}; color: white; padding: 4px 8px; text-decoration: none; border-radius: 3px; font-size:12px; font-weight:bold;'>공고 시스템 이동</a></p>
                </div>
                """
        html_content += "</body></html>"

    # 이메일 전송 파이프라인 기동 (Single To Header 방식으로 통일)
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = ", ".join(RECEIVERS) # 받는 사람란에 다인원 주소 동시 노출 연동
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVERS, msg.as_string())
            
        print(f"✅ 통합 알림 발송 성공! 대상자: {RECEIVERS}")
    except Exception as e:
        print(f"❌ 통합 알림 발송 실패: {e}", file=sys.stderr)

if __name__ == "__main__":
    build_html_and_dispatch()
