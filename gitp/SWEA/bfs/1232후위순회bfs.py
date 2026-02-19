for tc in range(1,11):
    try:
        line = input().strip()
        if not line: break
        N = int(line)
        tree_char = [0]*(N+1)
        left_char = [0]*(N+1)
        right_char = [0]*(N+1)

        for _ in range(N):
            info = input().split()
            idx = int(info[0])
            #애초에 길이가 4가 되어야 연산자가 존재함
            if len(info)==4:
                tree_char[idx]= info[1]
                left_char[idx]= int(info[2])
                right_char[idx]= int(info[3])
            else:
                tree_char[idx]=float(info[1])

        #이건 좌우 다 탐색되서 돌아올 때 까지 중간 계산 안하는 후위 순회 기반 계산 함수
        result=[]
        def in_order(node):
            if isinstance(tree_char[node],float): #실수로 나타내는거면 애초에 자식이 없는 노드이니 내려가다가 자식없는 노드 만나면 위로 올라가라는 뜻
                return tree_char[node]
            
            left_les = in_order(left_char[node]) #재귀로 왼쪽 내려가다가 자식없는 노드 만나면 위로 올라가고 애초에 내려갈때 저장된 이후 바로 다음 코드 시행됨
            right_les = in_order(right_char[node])#왼쪽으로 내려가는 것도 오른쪽으로 내려가는 것도 거의 잠깐 저장되어있고, 나중에 재귀로 호출됨

            #양쪽에서 재귀가 이뤄지는데 이게 한쪽에서 다 끝나고 재귀 이뤄지는게 아니라 
            #왼쪽이 return 해서 올라가면 그때 오른쪽으로 보낸다는건 안바뀜 올라가는 족족 오른쪽 보내봄 
            #오른쪽도 올라오는 족족 그 node를 +,-,*,/인지 판단해서 왼오 더해버림 

            '''
             구체적인 시뮬레이션: (10 - 5) 계산 과정트리에 1번 노드(-), 2번 노드(10), 3번 노드(5)가 있다고 가정해 봅시다.
             in_order(1) 시작: 1번 노드는 -입니다. "자, 왼쪽(2번)가서 돈 가져와!" 합니다.in_order(2) 실행: 2번 노드는 숫자 10.0입니다. 
             isinstance 조건에 걸려 **10.0을 들고 복귀(return)**합니다.이제 1번 노드의 left_les 변수에는 **10.0**이 저장됩니다.오른쪽 심부름: 1번 노드는 이제 "오른쪽(3번)가서 돈 가져와!" 합니다.in_order(3) 실행: 3번 노드는 숫자 5.0입니다.
            역시 5.0을 들고 복귀합니다.이제 1번 노드의 right_les 변수에는 **5.0**이 저장됩니다.드디어 합체 (피날레):1번 노드는 left_les(10.0)와 right_res(5.0)를 양손에 쥐었습니다.자기 연산자가 -인 걸 확인하고, $10.0 - 5.0$을 계산합니다.
            결과값인 5.0을 최종적으로 return 합니다.

            '''

            op = tree_char[node]
            if op == '+':
                return left_les+right_les
            if op =='-':
                return left_les-right_les
            if op=='*':
                return left_les*right_les
            if op=='/':
                return left_les/right_les
        final_result = in_order(1)
        print(f'#{tc} {int(final_result)}')

    except EOFError:
        break







