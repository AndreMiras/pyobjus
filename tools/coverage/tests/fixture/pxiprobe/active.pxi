cdef int c_helper(int value):
    if value > 0:
        return value + 10
    return -1

def helper(int value):
    return c_helper(value)

def never_called():
    return 999
