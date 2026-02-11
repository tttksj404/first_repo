#슬라이딩 윈도우 사용해서 윈도우 크기는 M이고 그 윈도우가 우측으로 이동하면서 회문 조건 
#revered 한거랑 값 같은지를 조건으로 같으면 break -> 윈도우 값들 출력
#아니면 다 돌고나서 none 출력


T = int(input())
for tc in range(1,T+1):
    N,M = map(int, input().split()) #N은 검사할 대상의 길이 / M은 지정된 회문 즉 윈도우의 길이
    N_list = input()
    window = list(N_list[:M]) #M개의 회문길이 창문 넣어놓기  #초반 M개값을 담아주기 
    found = False
    for idx in range(N-M+1): 
        if window == window[::-1]:
            print(f'#{tc} {"".join(window)}')
            found= True
            break

        if idx+M <N:
            window.pop(0)
            window.append(N_list[idx+ M])
    if not found:
        print(f'#{tc} NONE')



        





