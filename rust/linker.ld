/* PyKernel image layout: loaded at 1 MiB, identity mapped. */
ENTRY(_start)

SECTIONS
{
    . = 0x100000;
    __load_start = .;

    .boot : { KEEP(*(.boot)) }
    .text : { *(.text .text.*) }
    .rodata : ALIGN(4096) { *(.rodata .rodata.*) }
    .data : ALIGN(4096) {
        *(.data .data.*)
        *(.got .got.*)
        . = ALIGN(16);
    }
    __load_end = .;

    .bss : ALIGN(4096) {
        __bss_start = .;
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(16);
        __bss_end = .;
    }
    __kernel_end = .;

    /DISCARD/ : { *(.eh_frame*) *(.note*) *(.comment*) }
}
