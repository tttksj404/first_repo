def rezero(num):
    if num<1:
        return 1
    elif num==1:
        return 1
    else: 
        return num*rezero(num-1)

N = int(input())
result = rezero(N)
print(result)
