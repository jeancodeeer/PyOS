#!/bin/sh
# Debug aid: which kernel function contains an address?   sh tools/sym.sh 0x101a92
elf=target/x86_64-unknown-none/release/pykernel
nm -n "$elf" | awk -v a="$1" 'BEGIN { t = strtonum(a) } { if (strtonum("0x" $1) <= t) last = $0 } END { print last }'
objdump -d --start-address=$(($1 - 48)) --stop-address=$(($1 + 16)) "$elf" | tail -16
