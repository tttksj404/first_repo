'''
우선 가장 큰 값 바로 양옆 먼저 터뜨려주기
터뜨려진 배열에서 또 가장 큰 값 양옆 터뜨려주기 여기까진 해당 터뜨리는 값 
양옆에 수 곱해주고 총합에 더해주기

그러다가 하나 남으면 그것만 더해주기 

->그러나 이렇게 리스트로 풀면 계속 탐색해서 최대값 찾고 삭제해서 재배열하고 다시 최대값 찾아서 리스트 크기 커지면 엄청난 
시간복잡도 

그래서 힙큐를 사용해서 바로 최대값만 맨날 꺼내올 수 있도록 만들어줌 
'''
'''
import heapq

def solve(arr,n):
    
    if n==0: return 0
    if n==1: return arr[0]

    #기본 힙 구성 코드 -> 이중 연결리스트 외워두기
    prev = [i-1 for i in range(n)] #왼쪽으로 리스트 맨 처음값  보다 더 앞에있는 벽인 -1되게 되고 
    nxt = [i+1 for i in range(n)]
    nxt[n-1]=-1 # 오른쪽으로 맨 마지막 값보다 더 나가서 벽을-1 되게 함 -1이라는건 이게 끝이라는소리
    deleted=[False]*n

    #힙큐 대기실에서 뽑으면 결국에 가장 우선순위의 힙을 쓰게됨 
    max_heap=[]
    for i in range(n):
        heapq.heappush(max_heap, (-arr[i],i))

    total_sum=0
    remain_count= n 

    #요소가 하나 남을 때까지만 반복해서 최대값 찾고 그 양옆 터뜨리고 터뜨린 값의 양옆 곱해서 더해주고 로직
    while remain_count>1: 
        val_neg , m_idx = heapq.heappop(max_heap) #값, 그 값의 인덱스 -> 힙에서 가장 우선순위가 높은 상자 1개가 나옴 

        #여기서 핵심 큐는 그냥 시간순서만 우선순위로 보지만 힙큐는 우선순위큐로 내가 정한 조건을 우선순위로 보기에 조건있는 큐
        if deleted[m_idx]: continue

        m_val = -val_neg #원래는 -안붙이면 최소값 구하게 되는데 힙 푸시 할때도 - 붙여서 최대값 구하는걸로 봤고 다시 불러올때도 -붙여서 최대값 보장


        #최대값의 왼쪽 터뜨리기 로직  터뜨리고 그 왼쪽의 왼, 오른쪽 곱해주는 로직
        l_idx = prev[m_idx] 
        if l_idx != -1: #위에서 -1은 맨 앞보다 앞인 벽 아니면 맨 뒤보다 뒤인 벽이라고 설명 따라서 최대값의 왼쪽이 벽인지 물어봄
            ll_idx = prev[l_idx] #최대값의 왼쪽값의 왼쪽값 

            if ll_idx != -1: #왼쪽값의 왼쪽값이 맨 초반값보다 앞선 벽이 아니라는 설정 
                total_sum+= (arr[ll_idx]*m_val) #결국 최대값의 왼쪽값의 왼,오른쪽은 왼왼 * 최대값 
            else:
                total_sum+= m_val #왼쪽 끝이면 최대값만 더해주게됨

            deleted[l_idx]= True #어쨋든 삭제되어서 표시
            remain_count -=1 #남은 개수 하나 빼주기  실제로 리스트를 변환시키면 그만큼 다시 계산필요해서 그냥 삭제 했다고만 치는것
            prev[m_idx]=ll_idx #최대값의 왼쪽값은 삭제 되었으므로 그 왼왼값이 왼쪽값이 되는것 삭제된거 없애주고 그사이 매워주기
            if ll_idx !=-1: #-1 자체를 벽으로 둔 것 맨 초반값이 아님 
                nxt[ll_idx]=m_idx #여긴 터뜨려진 값 제외하고 왼왼 값 다음 인덱스가 m_idx 현재 값(최대값)이라는 것 
        
        r_idx = nxt[m_idx]
        if r_idx != -1:
            rr_idx = nxt[r_idx] # R의 오른쪽(RR) 찾기
            
            if rr_idx != -1:
                total_sum += (m_val * arr[rr_idx]) # M * RR 곱해서 더하기
            else:
                total_sum += m_val # 오른쪽 끝이면 그냥 M만 더하기
            
            # R 삭제 처리 및 연결 수정 (M과 RR을 직접 잇기)
            deleted[r_idx] = True
            remain_count -= 1
            nxt[m_idx] = rr_idx
            if rr_idx != -1:
                prev[rr_idx] = m_idx
        # 최대값 M은 아직 살아있으니 다시 힙에 넣기 어짜피 최대값은 마지막까지 남아있음 
        heapq.heappush(max_heap,(val_neg,m_idx))
    for i in range(n):
        if not deleted[i]: #삭제된 값이 아니고 마지막에 하나남은 값이라면 총합에 그 값만 더해주기 
            #여기선 진짜 삭제한게 아니고 deleted로 임의로 삭제했다고 표시만 해놔서 전수탐색 해야지 남아있는한개가 뭔지 알 수 있음
            total_sum+=arr[i]
            break
    return total_sum


T= int(input())
for tc in range(1,T+1):
    N=int(input())
    ballons= list(map(int,input().split()))

    print(f'#{tc} {solve(ballons,N)}')
'''

'''
위의 방식대로 풀면 절대적인 최대값은 보장하지 못함 

그냥 전체 전수조사 해보고 최대값만 남겨놓는 방식이 필요
'''

def get_max_score(current_balloons):
    # 1. 탈출 조건: 풍선이 하나도 없으면 0점 반환
    if not current_balloons:
        return 0
    
    # 풍선이 딱 하나 남았다면 그 풍선의 숫자가 곧 점수
    if len(current_balloons) == 1:
        return current_balloons[0]

    max_result = 0

    # 2. 모든 풍선을 하나씩 터뜨려보기 (순회)
    for i in range(len(current_balloons)):
        # i번째 풍선을 터뜨렸을 때 얻는 점수 계산 (사용자님 로직)
        if i == 0:
            # 맨 왼쪽 풍선을 터뜨리면 오른쪽 이웃 점수만 얻음
            score = current_balloons[1]
        elif i == len(current_balloons) - 1:
            # 맨 오른쪽 풍선을 터뜨리면 왼쪽 이웃 점수만 얻음
            score = current_balloons[i-1]
        else:
            # 중간 풍선을 터뜨리면 양옆의 곱을 얻음
            score = current_balloons[i-1] * current_balloons[i+1]
        
        # 3. 실제로 풍선을 터뜨리고 남은 리스트 만들기
        # i번째만 쏙 빼고 나머지를 합침 합치는 구조 중요!! 외워두기 
        remains = current_balloons[:i] + current_balloons[i+1:] 
        
        # 4. 재귀 호출: 남은 풍선들로 다시 게임을 해서 얻는 점수 더하기 호출 방식도 중요 외워두기 !! 
        total = score + get_max_score(remains)
        
        # 5. 여태까지 나온 점수 중 가장 큰 값으로 업데이트
        if total > max_result:
            max_result = total
            
    return max_result



T= int(input())
for t in range(1, T + 1):
    N = int(input())
    balloons = list(map(int, input().split()))
    
    result = get_max_score(balloons)
    print(f"#{t} {result}")
