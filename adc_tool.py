from fractions import Fraction

#     VIN
#      |
#     +-+
#     | |
#     | | R1
#     +-+
#      |
#      o--- ADC
#      |
#     +-+
#     | |
#     | | R2
#     +-+
#      |
#     GND
#
#


R1 = 10
R2 = 3.6

Vref = 3.3

bits = 10

adc_range = (2**bits)-1


divider = (R1+R2)/R2

scale = divider * Vref / adc_range

print("Scale:", scale)

frac = Fraction(scale)
print("Frac:", frac)

frac_limit = frac.limit_denominator((2**16)-1)
print("with limit:", frac_limit )

error = abs(frac_limit-frac)/frac
error = float(error)

print("error:", error*100, "%")


