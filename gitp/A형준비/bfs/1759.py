# 1. 입력 받기 (import sys 없이 기본 input 사용)
L, C = map(int, input().split())
# 입력받은 문자들을 리스트로 만들고, 사전순으로 미리 정렬합니다.
# 미리 정렬해두면 나중에 조합을 뽑을 때 자동으로 오름차순이 유지됩니다.
chars = sorted(input().split())

# 2. 모음/자음 조건을 만족하는지 검사하는 함수
def is_valid(password):
    vowels = "aeiou"
    v_count = 0  # 모음 개수
    c_count = 0  # 자음 개수
    
    for char in password:
        if char in vowels:
            v_count += 1
        else:
            c_count += 1
            
    # 문제 조건: 모음 1개 이상 AND 자음 2개 이상
    if v_count >= 1 and c_count >= 2:
        return True
    else:
        return False

# 3. 암호를 생성하는 재귀 함수 (백트래킹)
# start: 탐색을 시작할 인덱스 (중복 방지용)
# path: 현재까지 만들어진 암호 리스트
def solve(start, path):
    # [재귀 종료 조건]
    # 암호의 길이(L)가 목표치에 도달했다면
    if len(path) == L:
        # 리스트 형태인 path를 문자열로 합쳐줍니다.
        result = "".join(path)
        # 조건에 맞는지 확인 후 출력
        if is_valid(result): #true인지 여부 
            print(result)
        return

    # [탐색 수행]
    # 현재 위치(start)부터 전체 문자 개수(C)까지 반복
    for i in range(start, C):
        # 1. 문자를 하나 선택해서 path에 넣습니다.
        path.append(chars[i])
        
        # 2. 다음 문자를 뽑으러 재귀 호출 (i + 1 을 넘겨줌으로써 현재 뽑은 것 이후만 보게 함)
        solve(i + 1, path)
        
        # 3. 재귀가 끝난 후, 다시 돌아왔을 때는 방금 넣었던 문자를 빼줍니다 (백트래킹의 핵심)
        path.pop()

# 4. 메인 실행 부분
# 0번 인덱스부터 시작하며, 빈 리스트로 탐색을 시작합니다.
solve(0, [])