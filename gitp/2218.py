list_of_book = [
    '장화홍련전',
    '가락국 신화',
    '온달 설화',
    '금오신화',
    '이생규장전',
    '만복자서포기',
    '수성지',
    '백호집',
    '원생몽유록',
    '홍길동전',
    '장생전',
    '도문대작',
    '옥루몽',
    '옥련몽',
]

rental_book = [
    '장생전',
    '위대한 개츠비',
    '원생몽유록',
    '이생규장전',
    '데미안',
    '장화홍련전',
    '수성지',
    '백호집',
    '난중일기',
    '홍길동전',
    '만복자서포기',
]
'''
missing_list = []
for now_book in rental_book:
    if now_book not in list_of_book:
        missing_list.append(now_book)
        print(f'{now_book} 을/를 보충하여야 합니다.')
       
'''
    #[표현식 for 항목 in 반복가능객체 if 조건문]

    #표현식: 새로운 리스트에 담길 요소가 될 값이나 계산식입니다.

missing_list = [now_book for now_book in rental_book if now_book not in list_of_book]
#리스트 컴프리헨션을 통해 append 안하고도 리스트에 넣을 수 있음 


for now_book in missing_list:
    print(f'{now_book} 을/를 보충하여야 합니다.')
        
if not missing_list:
    print("모든 도서가 대여 가능한 상태입니다.")