'''
||||||이렇게 나오면 그냥 pass ()이게 어디서도 없다면 그냥 넘어가기 
무조건 "(" 혹은 ")"가 있는데 "("이면 오른쪽에  |있다면 공 가능 +=1
")" 이라면 왼쪽에 |있다면 공 가능 +=1

이미()있다면 +=1 


'''


T = int(input())
for tc in range(1,T+1):
    field = list(input().strip())
    ball_count = 0
    start_idx = 0
    for idx in range(start_idx,len(field)-1):
        if field[idx] == "(" and field[idx+1] ==")":
            ball_count+=1
        elif field[idx] == "(" and field[idx+1] =="|":
            ball_count+=1
        elif field[idx] =="|" and field[idx+1] ==")":
            ball_count+=1
        
    print(f'#{tc} {ball_count}')


