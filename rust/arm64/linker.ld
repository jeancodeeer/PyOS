/* PyKernel on ARM64: a position-independent image linked at 0; the UEFI
   loader (boot/aarch64-efi) puts it anywhere in RAM and applies .rela.dyn. */
ENTRY(_start)

SECTIONS
{
    . = 0;
    __load_start = .;
    .text : { KEEP(*(.text.boot)) *(.text.vectors) *(.text .text.*) }
    .rodata : ALIGN(4096) { *(.rodata .rodata.*) }
    .data.rel.ro : ALIGN(16) { *(.data.rel.ro .data.rel.ro.*) }
    .dynamic : { *(.dynamic) }
    .got : { *(.got .got.*) }
    .rela.dyn : { *(.rela.dyn) *(.rela.*) }
    .data : ALIGN(4096) { *(.data .data.*) . = ALIGN(16); }
    __load_end = .;
    .bss : ALIGN(4096) {
        __bss_start = .;
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(16);
        __bss_end = .;
    }
    __kernel_end = .;
    /DISCARD/ : { *(.eh_frame*) *(.note*) *(.comment*) *(.interp) }
}
