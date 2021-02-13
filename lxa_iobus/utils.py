def array2int(a):
    out = 0

    for i in range(len(a)):
        out |= a[i] << (i*8)

    return out


def int2array4(c):
    out = [0]*4

    for i in range(4):
        out[i] = 0xff & (c >> (i*8))

    return out
