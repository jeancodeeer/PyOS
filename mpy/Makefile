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
WEBP_ARCH = -mno-sse4.1 -mno-sse4.2 -mno-avx -mno-avx2
endif

CFLAGS += $(INC) -std=gnu99 -Wall -O2 -DNDEBUG \
	-ffreestanding $(ARCH_CFLAGS) \
	-fno-stack-protector -fno-stack-clash-protection \
	-U_FORTIFY_SOURCE -fno-asynchronous-unwind-tables -fno-unwind-tables \
	-fno-common -ffunction-sections -fdata-sections

# audio and video decoders (third-party, see media/ and THIRD_PARTY.md)
MEDIA_C = $(wildcard media/h264bsd/*.c) $(wildcard media/aac/*.c)
WEBP_C = $(wildcard media/webp/src/dec/*.c) $(wildcard media/webp/src/dsp/*.c) $(wildcard media/webp/src/utils/*.c)
MEDIA_C += $(WEBP_C)

# JavaScript: QuickJS (see js/quickjs and THIRD_PARTY.md) and the C library bits it needs
JS_C = js/quickjs/quickjs.c js/quickjs/libregexp.c js/quickjs/libunicode.c js/quickjs/cutils.c \
	js/quickjs/dtoa.c js/shim.c

SRC_C = \
	mphal.c \
	modkernel.c \
	modgfx.c \
	modmedia.c \
	arena.c \
	modaes.c \
	modjs.c \
	$(JS_C) \
	$(MEDIA_C) \
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

SRC_QSTR += mphal.c modkernel.c modgfx.c modmedia.c modaes.c modjs.c mpthread.c \
	readline.c \
	shared/runtime/pyexec.c \
	shared/runtime/sys_stdio_mphal.c \

OBJ = $(PY_O) $(addprefix $(BUILD)/, $(SRC_C:.c=.o))

# the third-party decoders: their own warnings are theirs; Arduino.h/pgmspace.h shims for Helix
$(addprefix $(BUILD)/, $(MEDIA_C:.c=.o)): CFLAGS += -w -Imedia/shim -Imedia/h264bsd -O2 -DUSE_DEFAULT_STDLIB
$(addprefix $(BUILD)/, $(WEBP_C:.c=.o)): CFLAGS += -Imedia/webp $(WEBP_ARCH) -DWEBP_DISABLE_NEON=1
$(addprefix $(BUILD)/, $(JS_C:.c=.o)): CFLAGS += -w -O2 -DPYKERNEL -DCONFIG_VERSION=\"2026-06-04\" -D_GNU_SOURCE

all: $(BUILD)/libmicropython.a

include $(TOP)/py/mkrules.mk
