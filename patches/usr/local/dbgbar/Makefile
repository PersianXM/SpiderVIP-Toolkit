# Makefile -- Engineering Debug Status Bar (dbgbar) for Spider VIP / HiSilicon
#
# Cross-compile for the receiver's ARM (arm-hisiv-linux / arm-linux-gnueabi*).
# Override CROSS to match your toolchain, e.g.:
#     make CROSS=arm-hisiv500-linux-
#     make CROSS=arm-linux-gnueabihf-
#
# The receiver rootfs is the small HiSilicon Linux; we link statically-friendly
# libc calls only (no external deps: no freetype, no ncurses, no libcurl).

CROSS   ?= arm-linux-gnueabihf-
CC       = $(CROSS)gcc
STRIP    = $(CROSS)strip

# Size/perf oriented: -Os, no exceptions, tiny. -march left to toolchain default.
CFLAGS  ?= -Os -Wall -Wextra -std=gnu99 -ffunction-sections -fdata-sections \
           -fno-strict-aliasing -pipe
LDFLAGS ?= -Wl,--gc-sections

OBJ = main.o config.o providers.o render.o
BIN = dbgbar

all: $(BIN)

$(BIN): $(OBJ)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJ)
	$(STRIP) $@ || true
	@echo "built $(BIN):"; ls -l $(BIN)

%.o: %.c dbgbar.h
	$(CC) $(CFLAGS) -c -o $@ $<

# host build for quick syntax/logic checks (renders to /dev/fb1 only on device)
host:
	cc -Os -Wall -Wextra -std=gnu99 -DHOST_BUILD -o dbgbar-host \
	   main.c config.c providers.c render.c

clean:
	rm -f $(OBJ) $(BIN) dbgbar-host

.PHONY: all host clean
