def array2int(a):
    return sum((b << (8 * i)) for i, b in enumerate(a))


def int2array(c, octets=4):
    return list(((c >> (i * 8)) & 0xff) for i in range(octets))
