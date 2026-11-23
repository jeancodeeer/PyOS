# Builds the MicroPython VM + PyKernel glue into libmicropython.a
# (freestanding x86_64, System V ABI). Run through tools/build.py.

MPTOP ?= ../vendor/micropython
BUILD ?= ../build/mpy

include $(MPTOP)/py/mkenv.mk

QSTR_DEFS = qstrdefsport.h
MICROPY_VFS_FAT = 1

include $(TOP)/py/py.mk
include $(TOP)/extmod/extmod.mk

INC += -Ilibc -I. -I$(TOP) -I$(BUILD)

CFLAGS += $(INC) -std=gnu99 -Wall -O2 -DNDEBUG \
	-ffreestanding -fno-pie -fno-pic -mno-red-zone -mcmodel=small \
	-fno-stack-protector -fno-stack-clash-protection -fcf-protection=none \
	-U_FORTIFY_SOURCE -fno-asynchronous-unwind-tables -fno-unwind-tables \
	-fno-common -ffunction-sections -fdata-sections

SRC_C = \
	mphal.c \
	modkernel.c \
	modgfx.c \
	mpthread.c \
	shared/libc/printf.c \
	shared/libc/string0.c \
	readline.c \
	shared/runtime/pyexec.c \
	shared/runtime/stdout_helpers.c \
	shared/runtime/interrupt_char.c \
	shared/runtime/gchelper_generic.c \
	shared/runtime/sys_stdio_mphal.c \
	shared/timeutils/timeutils.c \
	$(SRC_LIB_LIBM_DBL_C) \
	$(SRC_LIB_LIBM_DBL_SQRT_SW_C) \

SRC_QSTR += mphal.c modkernel.c modgfx.c mpthread.c \
	readline.c \
	shared/runtime/pyexec.c \
	shared/runtime/sys_stdio_mphal.c \

OBJ = $(PY_O) $(addprefix $(BUILD)/, $(SRC_C:.c=.o))

all: $(BUILD)/libmicropython.a

include $(TOP)/py/mkrules.mk
