def check_win(counts):
    #0부터 9까지 순회하며 확인
    for i in range(10):
        if counts[i]>=3:
            return True
        
        if counts[i]>=1 and counts[i+1]>=1 and counts[i+2]>=1:
            return True
    return False
        

T=int(input())
for tc in range(1,T+1):
    cards = list(map(int, input().split()))
    p1_counts= [0]*12 #교대로 카드 가져가기 먼저 player1 그다음 player2 
    p2_counts= [0]*12 #미리 카운트를 셀 리스트 만들어 놓기 

    winner=0
    
    for i in range(12):
        card = cards[i]

        if i%2 ==0: #순서 따로 정해줄 필요없이 애초에 짝수먼저나오고 그다음 홀수나옴 그 순서대로 하면 차례로 번갈아가며 확인가능
            p1_counts[card]+=1
            if check_win(p1_counts):
                winner=1
                break
        else:
            p2_counts[card]+=1
            if check_win(p2_counts):
                winner=2
                break


    print(f'#{tc} {winner}')