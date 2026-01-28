import requests

# 1. API 호출 설정
url = "http://finlife.fss.or.kr/finlifeapi/depositProductsSearch.json"
api_key = ""

params = {
    'auth': api_key,
    'topFinGrpNo': '020000',
    'pageNo': '1'
}

# 2. 데이터 가져오기
response = requests.get(url, params=params)

if response.status_code == 200: #주소를 제대로 찾았을 경우 200임 그래서 조건 실행
    data = response.json() # JSON을 파이썬 딕셔너리로 변환
    
    if data['result']['err_cd'] == '000':
        base_list = data['result']['baseList']
        option_list = data['result']['optionList']
        
        print(f"조회 성공! 총 {data['result']['total_count']}개의 상품이 검색되었습니다.\n")

        # 3. 상품 정보를 빠르게 찾기 위해 딕셔너리로 재구성
        # { '상품코드': {'은행': '우리은행', '상품명': '예금A', '금리정보': []} }
        product_dict = {}
        for base in base_list:
            cd = base['fin_prdt_cd']
            product_dict[cd] = {
                'bank': base['kor_co_nm'],     #bank : 우리은행 
                'name': base['fin_prdt_nm'],   #name : 예금A 
                'options': []   #하나의 상품에 여러개의 금리가 매칭되어서 일반변수가 아닌 리스트로 둬서 안 덮어씌어지게 
            }

        # 4. 금리 옵션(optionList)을 해당 상품에 매칭 
        for option in option_list: #옵션 리스트의 옵션들 전부 꺼내옴 
            cd = option['fin_prdt_cd']  #financial product code = 금융상품 코드  금융상품 코드를 통해 상품 판별가능 
            if cd in product_dict: #만약 그 금융상품 코드의 상품이 우리 api의 상품정보 딕셔너리에 있다면 저축기간/기본금리/우대금리 불러옴
                opt_info = {
                    'term': option['save_trm'],     # 저축 기간
                    'rate': option['intr_rate'],    # 기본 금리
                    'rate2': option['intr_rate2']   # 우대 금리
                }
                product_dict[cd]['options'].append(opt_info) #옵션 리스트에 여러개의 금리정보 append 추가 

        # 5. 결과 출력
        for cd, info in product_dict.items():
            print(f"[{info['bank']}] {info['name']}")
            for opt in info['options']: #product_dict안에 있는 dict의 options 즉 여러개의 금리를 반복해서 전부 불러옴
                print(f"  - {opt['term']}개월: 기본 {opt['rate']}% / 최고 {opt['rate2']}%")
            print("-" * 50) #하나의 상품에 대해서 반복 다하고 ----로 구분 그 위 for cd, info로 올라가서 다시 반복 
    else:
        print(f"에러 발생: {data['result']['err_msg']}")