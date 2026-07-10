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
# 💡 수신처 리스트 통일 (To 창에 한 번에 묶여서 단일 발송됨)
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

KEYWORDS = ['위성', '영상', '공간정보']

# ==========================================
# 2. 다비오 고도화 스코어링 & 네거티브 필터링
# ==========================================
# 💡 [요청 반영] 불필요한 사업을 원천 차단하기 위한 네거티브 키워드 대폭 확장
NEGATIVE_KEYWORDS = [
    "장치", "기념", "콘텐츠", "설치", "문화", "의료", "홍보", "방송", "초음파", "여행", 
    "시설", "의학", "드라마", "스포츠", "자막", "행사", "제조설비", "공장생산", "공장등록", 
    "단순제조", "탑재체", "부품", "수리", "정비", "기체", "배터리", "하드웨어", "청소", "폐기물", "구매"
]

# 💡 [요청 반영] 다비오 핵심 사업(무인, 관측, 해양 등)을 무조건 상으로 올리는 가중치
HIGH_WEIGHT_KEYWORDS = ["영상", "분석", "AI", "인공지능", "공간정보", "알고리즘", "플랫폼", "소프트웨어", "SW", "디지털트윈", "데이터", "정제", "무인", "관측", "해양", "검보정"]
MID_WEIGHT_KEYWORDS = ["위성", "드론", "무인기", "정찰", "감시", "시스템", "활용방안", "연구", "정보", "구축"]

def evaluate_bid_grade(title):
    clean_title = title.replace(" ", "")
    
    # 1. 강력한 네거티브 필터 (원본 텍스트 및 공백 제거 텍스트 교차 검증)
    for nk in NEGATIVE_KEYWORDS:
        if nk in title or nk in clean_title:
            return -1, "제외"

    score = 0
    # 2. 가중치 점수 합산
    for hk in HIGH_WEIGHT_KEYWORDS:
        if hk in title: score += 30
    for mk in MID_WEIGHT_KEYWORDS:
        if mk in title: score += 15

    # 3. 도메인 복합 시너지 보너스 (압도적 변별력)
    if "위성" in title and ("영상" in title or "데이터" in title or "검보정" in title):
        score += 15
    if "무인" in title and ("관측" in title or "해양" in title):
        score += 15

    # 4. 등급 판정
    if score >= 50:
        return score, "상 (핵심 타겟) 🎯"
    elif score >= 20:
        return score, "중 (검토 권장) 🔍"
    else:
        return score, "하 (단순 키워드) 💡"

# ==========================================
# 3. 데이터 융합 엔진 (D2B 누락 버그 완벽 해결)
# ==========================================
def collect_and_fuse_bids():
    kst_now = datetime.utcnow() + timedelta(hours=9)
    seven_days_ago = kst_now - timedelta(days=7)
    
    g2b_start = seven_days_ago.strftime('%Y%m%d0000')
    g2b_end = kst_now.strftime('%Y%m%d2359')
    
    # D2B 전용 날짜 포맷 (YYYYMMDD)
    d2b_date_start = seven_days_ago.strftime('%Y%m%d')
    d2b_date_end = kst_now.strftime('%Y%m%d')

    master_container = {
        "상 (핵심 타겟) 🎯": {},
        "중 (검토 권장) 🔍": {},
        "하 (단순 키워드) 💡": {}
    }

    keyword_str = ", ".join(KEYWORDS)

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

        # Part B: 국방전자조달(D2B) 수집 엔진 (누락 원인 완벽 해결)
        keyword_encoded = urllib.parse.quote(keyword)
        for api_tag, url in D2B_ENDPOINTS.items():
            # 💡 [핵심 버그 수정 1] inqryBgnDate 파라미터를 강제 주입하여 7일 치를 모두 가져오도록 조치!
            full_url = (
                f"{url}?serviceKey={SERVICE_KEY}&pageNo=1&numOfRows=100&bidNm={keyword_encoded}"
                f"&inqryBgnDate={d2b_date_start}&inqryEndDate={d2b_date_end}"
            )
            try:
                res = requests.get(full_url, timeout=15)
                if res.status_code == 200:
                    root = ET.fromstring(res.content)
                    items = root.findall('.//item')
                    
                    for item in items:
                        try:
                            title = item.findtext('bidNm', '')
                            # 💡 [핵심 버그 수정 2] G2B 번호가 없으면 D2B 고유 공고번호(pblancNo)를 추출!
                            g2b_no = item.findtext('g2bPblancNo', '').strip()
                            d2b_no = item.findtext('pblancNo', '').strip()
                            bid_id = g2b_no if g2b_no else d2b_no
                            
                            # 발주기관 및 계약방식 조합
                            ornt = item.findtext('ornt', '-')
                            cntrct_mth = item.findtext('cntrctMth', '')
                            display_org = f"{ornt} | {cntrct_mth}" if cntrct_mth else ornt

                            # 💡 [핵심 버그 수정 3] None 값이 오더라도 무시하고 진행 중으로 처리!
                            clse_dt_str = item.findtext('rgstClseDt', '')
                            if clse_dt_str and clse_dt_str.lower() != 'none' and len(clse_dt_str) >= 12:
                                try:
                                    clse_dt = datetime.strptime(clse_dt_str[:12], "%Y%m%d%H%M")
                                    if kst_now > clse_dt: continue # 지난 공고는 스킵
                                    formatted_clse = f"{clse_dt_str[0:4]}-{clse_dt_str[4:6]}-{clse_dt_str[6:8]} {clse_dt_str[8:10]}:{clse_dt_str[10:12]}"
                                except Exception:
                                    formatted_clse = clse_dt_str
                            else:
                                formatted_clse = "None(마감 미정/진행중)"

                            score, grade = evaluate_bid_grade(title)
                            if score != -1:
                                bid_id_safe = bid_id if bid_id else title
                                master_container[grade][bid_id_safe] = {
                                    'bidNtceNm': title,
                                    'display_org': display_org,
                                    '_api_type': f"D2B {api_tag}",
                                    'formatted_url': 'https://www.d2b.go.kr/',
                                    'display_date': formatted_clse,
                                    'bidNtceNo': bid_id_safe,
                                    'prtcptLmtRgnNm': "국방특화",
                                    'indstrytyLmtYn': "N"
                                }
                        except Exception:
                            continue
            except Exception:
                continue

    return master_container, keyword_str

# ==========================================
# 4. HTML 리포트 UI 생성 및 동시 전송
# ==========================================
def build_html_and_dispatch():
    container, keyword_str = collect_and_fuse_bids()
    total_count = sum(len(bids) for bids in container.values())
    
    subject = "📢 [나라장터/D2B 통합] 다비오 맞춤형 신규 용역/물품 공고 리포트"
    
    if total_count > 0:
        html_content = f"""
        <html>
        <body style='font-family: Arial, sans-serif; line-height: 1.6; color: #333;'>
            <h2>🚀 나라장터 및 국방 조달 맞춤형 인텔리전스</h2>
            <p>다비오 비즈니스 도메인 연관도 스코어링 알고리즘에 따라 총 <b>{total_count}건</b>의 진행 중인 유효 공고가 분류되었습니다.</p>
            <p style='font-size:12px; color:gray;'>조회 키워드: {keyword_str}</p>
        """
        
        for grade in ["상 (핵심 타겟) 🎯", "중 (검토 권장) 🔍", "하 (단순 키워드) 💡"]:
            items_dict = container[grade]
            if not items_dict: continue
                
            sorted_items = sorted(items_dict.values(), key=lambda x: x.get('display_date', ''), reverse=True)
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
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 발주기관 및 계약:</b> {item.get('display_org', '-')}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 지역제한:</b> <span style='color:#27ae60; font-weight:bold;'>{region}</span> | <b>공고번호:</b> {item.get('bidNtceNo', '-')}</p>
                    <p style='margin: 4px 0; font-size:13px;'><b>🔹 마감일시:</b> <span style='color: #e74c3c; font-weight:bold;'>{item.get('display_date', '-')}</span></p>
                    <p style='margin: 8px 0 0 0;'><a href='{item.get('formatted_url', '-')}' target='_blank' style='background-color: {border_color}; color: white; padding: 4px 8px; text-decoration: none; border-radius: 3px; font-size:12px; font-weight:bold;'>공고 시스템 이동</a></p>
                </div>
                """
        html_content += "</body></html>"
    else:
        html_content = f"<h3>진행 중인 '{keyword_str}' 관련 유효 물품/용역 공고가 없습니다.</h3>"

    # 이메일 동시 단일 발송
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
