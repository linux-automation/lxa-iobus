  .section .text._start
  .global _start
_start:

  # Ensure all outstanding memory accesses included
  # buffered write are completed before reset
  dsb

  # Application Interrupt and Reset Control Register
  # Trigger self reset
  ldr r2, .AIRCR
  ldr r3, .VECTKEY_RESET
  str r3, [r2]

  # Ensure all outstanding memory accesses included
  # buffered write are completed before reset
  dsb

.LOOP:
  b .LOOP
  
.ALIGN   8 

.AIRCR:
  .word 0xE000ED0C
.VECTKEY_RESET:
  .word 0x5fa0004

