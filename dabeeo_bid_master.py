def fetch_g2b_servc_bids() -> list:
    """타임아웃 방지 및 키 정제(줄바꿈 제거) 적용 수집 함수"""
    init_db()
    
    api_key = (
        os.getenv("G2B_API_KEY") or 
        os.getenv("SERVICE_KEY") or 
        os.getenv("G2B_SERVICE_KEY")
    )
    
    if not api_key:
        print("[WARN] G2B API 키가 환경변수에 존재하지 않습니다.")
        return []

    # 1. API 키 정제 (줄바꿈 %0A 및 공백 제거)
    api_key_clean = urllib.parse.unquote(api_key).strip().replace('\r', '').replace('\n', '')

    # 2. 최근 60일(2개월) 개시일 기준 조회
    now = datetime.now()
    inqrBeginDt = (now - timedelta(days=60)).strftime("%Y%m%d0000")
    inqrEndDt = now.strftime("%Y%m%d2359")

    # HTTPS 엔드포인트 사용
    url = "https://apis.data.go.kr/1230000/BidPublicInfoService02/getBidPstServcListInfoThng02"

    params = {
        'serviceKey': api_key_clean,
        'numOfRows': '200',     # 서버 과부하 방지를 위해 200건으로 조정
        'pageNo': '1',
        'inqrDiv': '1',         # 1: 공고 개시일 기준
        'inqrBeginDt': inqrBeginDt,
        'inqrEndDt': inqrEndDt,
        'type': 'json'
    }

    items = []
    try:
        # 타임아웃 30초 설정
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"[API HTTP ERROR] 응답 코드: {response.status_code}")
            return []

        try:
            data = response.json()
            items = data.get('response', {}).get('body', {}).get('items', [])
            
            if isinstance(items, dict):
                items = [items]
            elif not items:
                print(f"[API WARN] 최근 2개월간 수집된 데이터가 0건입니다.")
                return []
                
        except Exception as json_err:
            print(f"[API JSON ERROR] JSON 파싱 실패 (API 키 확인 필요): {json_err}")
            print(f"[API DEBUG] Raw Response: {response.text[:200]}")
            return []

    except Exception as e:
        print(f"[API Connection Error] 네트워크 호출 실패 (타임아웃 등): {e}")
        return []

    target_bids = []
    current_time_str = now.strftime("%Y-%m-%d %H:%M")
    
    print(f"\n--- 최근 2개월간 나라장터 원천 공고 {len(items)}건 검토 시작 ---")
    for item in items:
        bid_no = item.get('bidNtceNo', '')
        title = item.get('bidNtceNm', '')
        order_agency = item.get('ntceInsttNm') or item.get('dminsttNm') or '미지정 기관'
        bid_date = item.get('bidClseDt', '')
        reg_dt = item.get('bidNtceDt', '')
        bid_url = item.get('bidNtceDtlUrl') or f"https://www.g2b.go.kr:8081/ep/invitation/ui/bidGonggoDtl.do?bidNo={bid_no}"
        region = item.get('prtcLmtRgnNm', '전국')

        # 마감일 지난 공고 필터링
        if bid_date and bid_date < current_time_str:
            continue

        score, reasons = calculate_score(title)

        if score >= 1:
            print(f"[통과] 점수: {score:2d} | 마감일: {bid_date} | 이유: {reasons} | 공고명: {title}")
            target_bids.append({
                'bid_no': bid_no,
                'bid_name': title,
                'order_agency': order_agency,
                'bid_date': bid_date if bid_date else '진행중',
                'reg_dt': reg_dt,
                'bid_url': bid_url,
                'region': region,
                'score': score,
                'source': 'G2B'
            })

    # 정렬: 1순위 점수(내림차순), 2순위 게시일시(최신순 내림차순)
    target_bids.sort(key=lambda x: (x['score'], x['reg_dt']), reverse=True)

    print(f"--- 최종 마감전 유효 공고: {len(target_bids)}건 ---\n")
    return target_bids
