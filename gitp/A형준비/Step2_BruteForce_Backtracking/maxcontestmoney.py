def backtrack(array, depth):
    global big_num, visited_states
     
    state = ("".join(array), depth)
    if state in visited_states:
        return
    visited_states.add(state)
 
    if depth == int(change):
        result = int("".join(array))
        if result > big_num:
            big_num = result
        return
 
    n = len(array)
    for i in range(n):
        for j in range(i + 1, n):
 
            array[i], array[j] = array[j], array[i]
             
 
            backtrack(array, depth + 1)
 
            array[i], array[j] = array[j], array[i]
 
T_str = input()
if T_str:
    T = int(T_str)
    for tc in range(1, T + 1):
        num_str, change = input().split()
        numbers = list(num_str)
        big_num = -1
         
        visited_states = set()
         
        backtrack(numbers, 0)
        print(f"#{tc} {big_num}")