#!/bin/sh
# Boot the ARM64 ISO in QEMU (virt machine, UEFI firmware AAVMF):
#   tools/run_arm64.sh [build/snakeyos-arm64.iso] [extra qemu options]
# Needs: qemu-system-arm qemu-efi-aarch64 (Debian/Ubuntu package names).
ISO=${1:-build/snakeyos-arm64.iso}
[ $# -gt 0 ] && shift
VARS=build/aavmf_vars.fd
[ -f $VARS ] || cp /usr/share/AAVMF/AAVMF_VARS.fd $VARS
exec qemu-system-aarch64 -M virt,gic-version=2 -cpu cortex-a72 -m 1024 \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.fd \
  -drive if=pflash,format=raw,file=$VARS \
  -device ramfb -device qemu-xhci -device usb-kbd -device usb-tablet \
  -drive file=$ISO,media=cdrom,if=none,id=cd,readonly=on -device virtio-scsi-pci -device scsi-cd,drive=cd \
  -nic user,model=virtio-net-pci "$@"
