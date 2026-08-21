def fetch_g2b_servc_bids() -> list:
    """g2b_bot_email.py와 100% 규격이 맞추어진 G2B 수집 함수"""
    init_db()
    
    # 여러 환경변수 이름 중 존재하는 키를 자동으로 찾아 사용
    api_key = (
        os.getenv("G2B_API_KEY") or 
        os.getenv("SERVICE_KEY") or 
        os.getenv("G2B_SERVICE_KEY")
    )
    
    if not api_key:
        print("[WARN] G2B API 키(G2B_API_KEY / SERVICE_KEY)가 설정되지 않았습니다.")
        return []

    # url decoding 처리 (필요시)
    import urllib.parse
    api_key = urllib.parse.unquote(api_key)

    # 최근 3일간 공고 조회
    now = datetime.now()
    inqrBeginDt = (now - timedelta(days=3)).strftime("%Y%m%d0000")
    inqrEndDt = now.strftime("%Y%m%d2359")

    # API 호출 URL (오타 수정: getBidPstServcListInfoThng02)
    url = "http://apis.data.go.kr/1230000/BidPublicInfoService02/getBidPstServcListInfoThng02"
    params = {
        'serviceKey': api_key,
        'numOfRows': '100',
        'pageNo': '1',
        'inqrDiv': '1',
        'inqrBeginDt': inqrBeginDt,
        'inqrEndDt': inqrEndDt,
        'type': 'json'
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        items = data.get('response', {}).get('body', {}).get('items', [])
    except Exception as e:
        print(f"[API ERROR] 나라장터 API 호출 실패: {e}")
        return []

    target_bids = []
    
    print(f"\n--- 나라장터 수집 공고 {len(items)}건 스코어링 시작 ---")
    for item in items:
        bid_no = item.get('bidNtceNo', '')
        title = item.get('bidNtceNm', '')
        order_agency = item.get('ntceInsttNm') or item.get('dminsttNm') or '미지정 기관'
        bid_date = item.get('bidClseDt', '진행중')
        bid_url = item.get('bidNtceDtlUrl') or f"https://www.g2b.go.kr:8081/ep/invitation/ui/bidGonggoDtl.do?bidNo={bid_no}"
        region = item.get('prtcLmtRgnNm', '전국')

        score, reasons = calculate_score(title)
        
        print(f"[검토] 점수: {score:2d} | 공고명: {title} | 이유: {reasons}")

        if score >= 5:
            target_bids.append({
                'bid_no': bid_no,
                'bid_name': title,
                'order_agency': order_agency,
                'bid_date': bid_date,
                'bid_url': bid_url,
                'region': region,
                'score': score,
                'source': 'G2B'
            })

    print(f"--- 필터링 통과 공고: {len(target_bids)}건 ---\n")
    return target_bids
