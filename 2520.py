#전체 테스트 케이스 나눠서 반복 돌리기
#c우유 8 / y계란 8 /ssu설탕 4/ ssa소금 1 / f밀가루 9 / = 팬케이크 반죽 16
# b바나나 1개 -> 나눌 수 있음 1/3 *3 으로 쓸 수 있음
#gs딸기잼 30그램
#gc초콜릿 스프레드 25그램
# w호두 10개 

#우유 8 나누기 해서 몫과 나머지 모두 조건만족  여기서 각 숫자에 8,8,4,1,9씩 
#배주고 하나라도 0이 나오면 break? 숫자 한바퀴 밀가루 까지 조건 만족시 +=16해주기
#아님 그냥 하나라도 %==0 안되면 그때 그거 실수값으로 받고 16*(17/9)같이 그 실수 값으로
#나눠주면 팬케이크 반죽 실수형이 나오는데 그걸 int로 바꿔주면 가능 

#거기서  각 토핑 / 한 몫과 나머지를 int형으로 전환후 전부 더했을때 개수가
#최대 펜케이크 반죽 보다 작으면 그개 최대 개수
#만약 최대 팬케이크 반죽이 더 작으면 최대 팬케이크 반죽이 최대개수



test_case = input()
print()
for _ in range(int(test_case)):
    pancake_ingrediant = list(map(int, input().split()))
    topping = list(map(int, input().split())) #len 쓰려면 반드시 list

    min_ingrediant = 0
    pancake_base = 0
    #//로 몫만 봤을때 가장 작은 값 팬케이크 반죽의 기준
    for ind in range(len(pancake_ingrediant)):
        if ind ==0 or ind ==1: #무조건 or ,and 할땐 똑같이 앞에 식 써주기
            pancake_ingrediant[ind]/=8
        elif ind == 2:
            pancake_ingrediant[ind]/=4
        elif ind == 3:
            pancake_ingrediant[ind]/=1
        elif ind == 4:
            pancake_ingrediant[ind]/=9
    min_ingrediant += min(pancake_ingrediant)
    pancake_base += 16*min_ingrediant

    for ind in range(len(topping)):
        if ind ==0:
            topping[0]//=1
        elif ind ==1:
            topping[1]//=30
        elif ind ==2:
            topping[2]//=25
        else: 
            topping[3]//=10
    sum_toping = sum(topping)
    answer = 0
    if sum_toping > pancake_base:
        answer += pancake_base
    else:
        answer += sum_toping
    print(answer)

        

        


