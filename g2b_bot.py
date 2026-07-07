# g2b_bot.py
import requests
import json
from datetime import datetime, timedelta

# 💡 추후 슬랙 웹훅 주소가 발급되면 아래 빈칸('')에 주소를 넣으시면 됩니다!
SLACK_WEBHOOK_URL = '' 
SERVICE_KEY = '+emmedaZrwpwK2FqtKT9BiUA9/qWfUYkm3pFh/w95QRP5V6qSAjjO2dJaLJnOZ7KdAssIS6mspZr0STsYfv8dg=='
SEARCH_KEYWORD = '위성'
API_URL = 'http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch'

def send_slack(text):
    if not SLACK_WEBHOOK_URL:
        print("📢 슬랙 웹훅 URL이 아직 설정되지 않았습니다. 콘솔에 결과를 출력합니다.")
        print(text)
        return
    payload = {"text": text}
    headers = {'Content-Type': 'application/json'}
    requests.post(SLACK_WEBHOOK_URL, headers=headers, data=json.dumps(payload))

# 날짜 계산 (최근 7일)
today = datetime.now()
seven_days_ago = today - timedelta(days=7)
inqry_bgn_dt = seven_days_ago.strftime('%Y%m%d0000')
inqry_end_dt = today.strftime('%Y%m%d2359')

params = {
    'ServiceKey': SERVICE_KEY,
    'type': 'json',               
    'numOfRows': '50',            
    'pageNo': '1',                
    'inqryDiv': '1',              
    'inqryBgnDt': inqry_bgn_dt,   
    'inqryEndDt': inqry_end_dt,   
    'bidNtceNm': SEARCH_KEYWORD,  
    'bidClseExcpYn': 'Y'          
}

response = requests.get(API_URL, params=params)

if response.status_code == 200:
    data = response.json()
    try:
        total_count = data['response']['body']['totalCount']
        items = data['response']['body']['items']
        items = sorted(items, key=lambda x: x.get('bidNtceDt', ''), reverse=True)
        
        message = f"🚀 *나라장터 [{SEARCH_KEYWORD}] 신규 용역 공고 알림*\n"
        message += f"✅ 최근 일주일간 등록된 진행 중인 공고: {total_count}건\n"
        message += "=" * 40 + "\n"
        
        for idx, item in enumerate(items, 1):
            message += f"*{idx}. {item.get('bidNtceNm', '공고명 없음')}*\n"
            message += f" 🔹 수요기관: {item.get('dminsttNm', '알 수 없음')}\n"
            message += f" 🔹 공고일시: {item.get('bidNtceDt', '-')}\n"
            message += f" 🔹 마감일시: {item.get('bidClseDt', '-')}\n"
            message += f" 🔗 <{item.get('bidNtceUrl', '-')}|공고 상세 보기>\n"
            message += "-" * 40 + "\n"
            
        send_slack(message)
    except KeyError:
        send_slack(f"ℹ️ [{SEARCH_KEYWORD}] 최근 일주일 내 등록된 신규 공고가 없습니다.")
