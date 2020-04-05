  .section .text._start
  .global _start
_start:
  
  # *SYSMEMREMAP = 2; // select user flash
  ldr r3, .SYSMEMREMAP
  mov r2, #2
  str r2, [r3]

  # get stack pointer
  movs r4, #0
  ldr r3, [r4]
  mov SP, r3

  # get entry pointer
  movs r4, #4
  ldr r3, [r4]
  blx r3

.ALIGN 8
.SYSMEMREMAP:
  .word 0x40048000
