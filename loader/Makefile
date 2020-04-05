
TARGETS = soft_reset.bin reset.bin
AS = arm-none-eabi-as
LD = arm-none-eabi-ld
CC = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
CFLAGS = "-march=armv6-m"

all: $(TARGETS)

%.bin: %.elf
	$(OBJCOPY) -O binary $< $@

%.elf: %.o
	$(LD) $< -o $@

%.o: %.s
	$(AS) -march=armv6-m $< -o $@

clean:
	rm $(TARGETS)
