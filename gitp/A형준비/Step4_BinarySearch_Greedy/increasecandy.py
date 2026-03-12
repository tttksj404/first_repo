'''
그리디임 


'''

T=int(input())
for tc in range(1,T+1):
    A,B,C = map(int,input().split())
    total=0
    possible=True
    if B>=C:
        total+=B-C+1
        B=C-1

    if A>=B:
        total+=A-B+1
        A=B-1
    
    if A<1 or B<1 or C<1:
        possible=False
   
    if possible==True:
        print(f'#{tc} {total}')
    else:
        print(f'#{tc} {-1}')


    

