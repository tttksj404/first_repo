import sys

# 표준 입력을 파일이나 터미널에서 읽기 위해 설정 (백준/SWEA 방식)
# input = sys.stdin.readline # 더 빠른 입력을 원할 때 사용

def is_palindrome(s):
    """문자열이 회문인지 확인하는 함수"""
    return s == s[::-1]

for _ in range(10):
    # 1. 테스트 케이스 번호 입력
    tc_num = input().strip() #strip()은 문자열 내부(중간)에 위치한 공백은 절대 안 건든다 
    #" a b c " -> "a b c"이런식으로 ""사이에 있는 공백 부분만 없애버림 
    
    # 2. 100x100 글자판 입력
    board = [input().strip() for _ in range(100)]
    
    # 3. 세로 검사를 쉽게 하기 위해 세로줄을 가로줄로 바꾼 전치 행렬 생성
    board_t = ["".join(row) for row in zip(*board)] #전치 행렬생성방법임 외우기 
    
    found = False #아직 회문을 찾지 못했다는 기본 값 
    # 4. 가장 긴 길이(100)부터 1까지 역순으로 조사
    for length in range(100, 0, -1): #한줄에서 잘라낼 수 있는 회문의 길이 자체를 역순탐색해서 max 필요없음
        if found:
            break
            
        for i in range(100): #행
            # 한 줄에서 길이 length만큼 잘라낼 수 있는 시작점(j)의 범위
            for j in range(100 - length + 1): 
                '''
                100cm 책상에서 90cm의 자를 옆으로 밀면서 검사하면 
                j가 시작점이고 끝점이 j+length인데 그래서 오른쪽 끝점인 j+length는 책상 끝인 100cm를 넘지 못한다
                그렇기에 j+length<=100 -> j<=100-length 즉 시작점이 가질 수 있는 최대값은 100-length가 됨 


                '''
                # 가로줄(행)에서 회문 검사
                if is_palindrome(board[i][j:j+length]): #슬라이딩 윈도우임 
                    '''
                    j를 j+length로 결정한건 예를 들어 j=0, length=5 이면 [0 : 5]가 되서 
                    0,1,2,3,4번 인덱스 즉 5개 글자를 가져오고, 결과적으로 length만큼 글자를 가져오게 된다 
                    따라서 length길이 만큼의 슬라이딩 윈도우 
                    어느 위치j 에서 시작하든지 우리가 원하는 길이(length)만큼의 부분 문자열 추출함 
                    '''
                    print(f"#{tc_num} {length}")
                    found = True #회문 찾았다는 값 
                    break
                
                # 세로줄(열)에서 회문 검사 (전치 행렬 이용)
                if is_palindrome(board_t[i][j:j+length]):
                    print(f"#{tc_num} {length}")
                    found = True
                    break
            if found:
                break