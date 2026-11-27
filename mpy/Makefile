# Builds the MicroPython VM + PyKernel glue into libmicropython.a
# (freestanding x86_64 or aarch64). Run through tools/build.py.
#   make            x86_64 (build/mpy)
#   make ARCH=aarch64   ARM64, with aarch64-linux-gnu-gcc (build/mpy-aarch64)

MPTOP ?= ../vendor/micropython
ARCH ?= x86_64
ifeq ($(ARCH),aarch64)
CROSS_COMPILE ?= aarch64-linux-gnu-
BUILD ?= ../build/mpy-aarch64
else
BUILD ?= ../build/mpy
endif

include $(MPTOP)/py/mkenv.mk

QSTR_DEFS = qstrdefsport.h
MICROPY_VFS_FAT = 1

include $(TOP)/py/py.mk
include $(TOP)/extmod/extmod.mk

INC += -Ilibc -I. -I$(TOP) -I$(BUILD)

ifeq ($(ARCH),aarch64)
# position independent: the UEFI loader (boot/aarch64) puts the kernel wherever RAM is free
ARCH_CFLAGS = -fPIE -mno-outline-atomics -mcmodel=small
else
ARCH_CFLAGS = -fno-pie -fno-pic -mno-red-zone -mcmodel=small -fcf-protection=none
endif

CFLAGS += $(INC) -std=gnu99 -Wall -O2 -DNDEBUG \
	-ffreestanding $(ARCH_CFLAGS) \
	-fno-stack-protector -fno-stack-clash-protection \
	-U_FORTIFY_SOURCE -fno-asynchronous-unwind-tables -fno-unwind-tables \
	-fno-common -ffunction-sections -fdata-sections

# JavaScript: QuickJS (see js/quickjs and THIRD_PARTY.md) and the C library bits it needs
JS_C = js/quickjs/quickjs.c js/quickjs/libregexp.c js/quickjs/libunicode.c js/quickjs/cutils.c \
	js/quickjs/dtoa.c js/shim.c

SRC_C = \
	modmedia.c \
	arena.c \
	modjs.c \
	$(JS_C) \
	shared/libc/printf.c \
	shared/libc/string0.c \
	shared/runtime/pyexec.c \
	shared/runtime/stdout_helpers.c \
	shared/runtime/interrupt_char.c \
	shared/runtime/gchelper_generic.c \
	shared/runtime/sys_stdio_mphal.c \
	shared/timeutils/timeutils.c \
	$(SRC_LIB_LIBM_DBL_C) \
	$(SRC_LIB_LIBM_DBL_SQRT_SW_C) \

SRC_QSTR += modmedia.c modjs.c \
	shared/runtime/pyexec.c \
	shared/runtime/sys_stdio_mphal.c \

OBJ = $(PY_O) $(addprefix $(BUILD)/, $(SRC_C:.c=.o))

# the third-party decoders: their own warnings are theirs; Arduino.h/pgmspace.h shims for Helix
$(addprefix $(BUILD)/, $(JS_C:.c=.o)): CFLAGS += -w -O2 -DPYKERNEL -DCONFIG_VERSION=\"2026-06-04\" -D_GNU_SOURCE

all: $(BUILD)/libmicropython.a

include $(TOP)/py/mkrules.mk
