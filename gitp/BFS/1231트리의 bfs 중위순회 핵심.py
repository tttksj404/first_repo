import sys

# 10개의 테스트 케이스가 고정으로 주어집니다.
for tc in range(1, 11):
    try:
        # N: 정점의 총 수
        line = sys.stdin.readline()
        if not line: break
        N = int(line.strip())
        
        # 정보를 담을 배열들 (1번부터 N번까지 사용) 1번부터라서 N+1로 배열 설정해주는 것 
        tree_char = [0] * (N + 1)
        left_child = [0] * (N + 1)
        right_child = [0] * (N + 1)
        
        # N줄에 걸쳐 데이터 입력 받기
        for _ in range(N):
            info = sys.stdin.readline().split()
            idx = int(info[0]) # 노드 번호
            tree_char[idx] = info[1] # 문자 저장
            
            # 왼쪽 자식이 있다면 저장 입력받은 값 길이 중 인덱스 0,1,2에서 2가 왼쪽이므로 
            if len(info) >= 3:
                left_child[idx] = int(info[2])
            # 오른쪽 자식까지 있다면 저장
            if len(info) == 4:
                right_child[idx] = int(info[3])
        
        # -------------------------------------------
        # 중위 순회(In-order) 함수 정의
        # -------------------------------------------
        result = []
        
        def in_order(node): #재귀의 스택 근데 한 방향이 아니라 다방향으로 미리 전부 보고 넘어가서 bfs임 
            if node == 0: # 자식이 없으면(0이면) 리턴
                return
            
            # 1. 왼쪽으로 먼저 쭉 내려가기 (Left) 이렇게 해서 쭉 내려가야 일단 왼쪽 부분 전부 스택 쌓임
            in_order(left_child[node])
            
            # 2. 더 이상 왼쪽이 없으면 현재 노드 읽기 (Root) 쌓인 스택을 맨 아래부터 해소해서 append함 스택 전부 해소전까지는 append 계속
            result.append(tree_char[node])
            
            # 3. 그 다음 오른쪽 확인하기 (Right) 왼쪽 스택 해소할때 그 스택에 대한 오른쪽도 같이 보게됨 
            in_order(right_child[node])

            #왼쪽 스택 다 쌓고, 스택 lifo 이므로 쌓인 재귀가 return만나서 왼쪽꺼가 아래서부터 위로 해소되는데 해소되며 
            # 그 값을 현재 노드로 append 해놓고 그 현재 노드의 다시 오른쪽 아래에 대한 스택을 쌓는다
            # 한마디로 왼쪽 스택은 아래서 위로 그러면서 노드값은 저장하며, 그 노드값의 오른쪽 아래 스택을 쌓고
            # 오른쪽 아래 스택을 다시 아래서 부터 위로 해소해주며 append 
            # 이 순서대로 들어가게됨  

        # 루트인 1번 노드부터 시작
        in_order(1)
        
        # 결과 출력
        print(f"#{tc} {''.join(result)}")
        
    except EOFError:
        break