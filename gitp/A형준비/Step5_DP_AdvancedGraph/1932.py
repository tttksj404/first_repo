"""
📍 [BOJ] 1932 정수 삼각형
> [학습 우선순위: Step 5 - DP/격자]
> 삼각형 꼭대기에서 바닥까지 내려오며 거치는 숫자의 최대 합을 구하라.

🔍 상세 분석:
- 각 층의 숫자들은 바로 위 층의 왼쪽 대각선이나 오른쪽 대각선에서 내려옵니다.
- **"현재 위치에 도달했을 때의 최대 합"**은 이전 층의 두 후보 중 더 큰 값에 현재 숫자를 더한 것입니다.

🏗️ 구현 체크리스트:
1. 삼각형 데이터를 리스트로 받는다.
2. 2층(index 1)부터 바닥까지 내려가며 값을 갱신한다.
3. 경계값 처리: 
   - 맨 왼쪽 칸은 바로 위 0번 칸에서만 온다.
   - 맨 오른쪽 칸은 바로 위 이전 칸에서만 온다.
   - 가운데 칸은 `max(왼쪽위, 오른쪽위)` 를 선택한다.

💡 학생 가이드:
- "따로 DP 테이블을 만들어야 하나요?" 
  -> 아니요, 입력받은 `triangle` 리스트 자체에 누적 합을 덮어쓰면 메모리를 아낄 수 있어 아주 효율적입니다.
"""

import sys
input = sys.stdin.readline

def solve():
    n = int(input())
    triangle = [list(map(int, input().split())) for _ in range(n)]
    
    # 두 번째 줄(index 1)부터 마지막 줄까지 내려가며 최적해를 누적
    for i in range(1, n):
        for j in range(len(triangle[i])):
            # 1. 현재 층의 맨 왼쪽인 경우: 바로 위의 맨 왼쪽(j=0)에서만 올 수 있음
            if j == 0:
                triangle[i][j] += triangle[i - 1][j]
            # 2. 현재 층의 맨 오른쪽인 경우: 바로 위의 맨 오른쪽(j-1)에서만 올 수 있음
            elif j == i:
                triangle[i][j] += triangle[i - 1][j - 1]
            # 3. 가운데 낀 경우: 왼쪽 위(j-1)와 오른쪽 위(j) 중 더 큰 것을 선택해서 내려옴
            else:
                triangle[i][j] += max(triangle[i - 1][j - 1], triangle[i - 1][j])
                
    # 마지막 바닥 층에 쌓인 값들 중 최댓값이 정답!
    print(max(triangle[n - 1]))

if __name__ == "__main__":
    solve()
