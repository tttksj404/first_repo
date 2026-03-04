#정의한 암호 패턴 (문자열)
a, b, c, d, e = "0001101", "0011001", "0010011", "0111101", "0100011"
f, g, h, i, j = "0110001", "0101111", "0111011", "0110111", "0001011"

T = int(input())

for tc in range(1, T + 1):
    # N: 세로, M: 가로
    N, M = map(int, input().split())
    
    # password: 전체 2차원 배열 입력
    password = [input().strip() for _ in range(N)]
    
    # 1. 암호가 들어있는 줄 하나만 찾기
    target_line = ""
    for r in range(N):
        if '1' in password[r]:
            target_line = password[r]
            break
            
    # 2. 뒤에서부터 처음 나오는 '1'을 찾아 끝 지점 잡기
    last_idx = 0
    for col in range(M - 1, -1, -1):
        if target_line[col] == '1':
            last_idx = col
            break
            
    # 3. new_password: 암호의 핵심 56비트만 문자열로 쏙 빼오기
    new_password = target_line[last_idx - 55 : last_idx + 1]
    
    # 4. answer: 7비트씩 잘라 해독한 숫자 8개를 담을 리스트
    answer = []
    for k in range(0, 56, 7):
        # window: 7비트씩 자른 문자열
        window = new_password[k : k + 7]
        
        # 영은이가 쓴 방식대로 하나씩 비교해서 answer에 추가
        if window == a: answer.append(0)
        elif window == b: answer.append(1)
        elif window == c: answer.append(2)
        elif window == d: answer.append(3)
        elif window == e: answer.append(4)
        elif window == f: answer.append(5)
        elif window == g: answer.append(6)
        elif window == h: answer.append(7)
        elif window == i: answer.append(8)
        elif window == j: answer.append(9)

    # 5. zzak_storage, hol_storage 계산 (문제 기준 홀수/짝수 위치)
    # 인덱스 0, 2, 4, 6은 사람 기준 1, 3, 5, 7번째 (홀수 자리)
    # 인덱스 1, 3, 5, 7은 사람 기준 2, 4, 6, 8번째 (짝수 자리)
    
    hol_storage = answer[0] + answer[2] + answer[4] + answer[6]
    zzak_storage = answer[1] + answer[3] + answer[5] + answer[7]
    
    # 6. ans: 검증 공식 결과
    ans = (hol_storage * 3) + zzak_storage
    
    # 7. 결과 출력
    if ans % 10 == 0:
        # 올바른 암호면 8개 숫자의 단순 합 출력
        print(f"#{tc} {sum(answer)}")
    else:
        # 틀린 암호면 0 출력
        print(f"#{tc} 0")