//! Machine bring-up: Multiboot entry in 32-bit protected mode, identity-map
//! the first 4 GiB with 2 MiB pages, enable SSE, switch to long mode, call
//! `kmain`. Also the common interrupt entry path. Nothing else lives in asm.

use core::arch::global_asm;

global_asm!(
    r#"
.section .boot, "ax"
.code32
.balign 8
mb_header:
    .long 0x1BADB002                    /* multiboot 1 magic            */
    .long 0x00010003                    /* address fields | meminfo | align */
    .long -(0x1BADB002 + 0x00010003)
    .long mb_header
    .long __load_start
    .long __load_end
    .long __bss_end
    .long _start

.global _start
_start:
    cli
    cld
    movl %eax, %ebp                     /* multiboot magic; %ebx = info */
    movl $__bss_start, %edi
    movl $__bss_end, %ecx
    subl %edi, %ecx
    shrl $2, %ecx
    xorl %eax, %eax
    rep stosl
    movl $boot_stack_top, %esp

    /* PML4[0] -> PDPT, PDPT[0..4] -> 4 page directories of 2 MiB pages */
    movl $boot_pdpt, %eax
    orl $3, %eax
    movl %eax, boot_pml4
    movl $boot_pd, %eax
    orl $3, %eax
    movl %eax, boot_pdpt
    addl $0x1000, %eax
    movl %eax, boot_pdpt+8
    addl $0x1000, %eax
    movl %eax, boot_pdpt+16
    addl $0x1000, %eax
    movl %eax, boot_pdpt+24
    xorl %ecx, %ecx
1:  movl %ecx, %eax
    shll $21, %eax
    orl $0x83, %eax                     /* present | writable | huge    */
    movl %eax, boot_pd(,%ecx,8)
    movl %ecx, %eax
    shrl $11, %eax
    movl %eax, boot_pd+4(,%ecx,8)
    incl %ecx
    cmpl $2048, %ecx
    jne 1b

    movl %cr4, %eax
    orl $0x620, %eax                    /* PAE | OSFXSR | OSXMMEXCPT    */
    movl %eax, %cr4
    movl $boot_pml4, %eax
    movl %eax, %cr3
    movl $0xC0000080, %ecx
    rdmsr
    orl $0x900, %eax                    /* EFER.LME | EFER.NXE          */
    wrmsr
    movl %cr0, %eax
    andl $0xFFFFFFFB, %eax              /* clear EM                     */
    orl $0x80000023, %eax               /* PG | NE | MP | PE            */
    movl %eax, %cr0
    lgdt boot_gdt_ptr
    ljmp $0x08, $long_mode

.code64
long_mode:
    movw $0x10, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %ss
    xorl %eax, %eax
    movw %ax, %fs
    movw %ax, %gs
    fninit
    movl %ebp, %edi
    movl %ebx, %esi
    call kmain
2:  hlt
    jmp 2b

.balign 16
boot_gdt:
    .quad 0
    .quad 0x00209A0000000000            /* 0x08: 64-bit code            */
    .quad 0x0000920000000000            /* 0x10: data                   */
boot_gdt_ptr:
    .word 23
    .long boot_gdt
    .long 0

.section .bss.boot, "aw", @nobits
.balign 4096
.global boot_pml4
boot_pml4:  .skip 4096
boot_pdpt:  .skip 4096
boot_pd:    .skip 16384
.global boot_stack
boot_stack: .skip 0x80000
.global boot_stack_top
boot_stack_top:

/* ---- interrupt entry: save state, call rust_isr(frame), restore ---- */
.section .text.isr, "ax"
.code64
isr_common:
    pushq %rax
    pushq %rcx
    pushq %rdx
    pushq %rbx
    pushq %rbp
    pushq %rsi
    pushq %rdi
    pushq %r8
    pushq %r9
    pushq %r10
    pushq %r11
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    cld
    movq %rsp, %rdi
    movq %rsp, %rbp
    subq $512, %rsp
    andq $-16, %rsp
    fxsave64 (%rsp)                     /* the Python VM uses SSE       */
    call rust_isr
    fxrstor64 (%rsp)
    movq %rbp, %rsp
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %r11
    popq %r10
    popq %r9
    popq %r8
    popq %rdi
    popq %rsi
    popq %rbp
    popq %rbx
    popq %rdx
    popq %rcx
    popq %rax
    addq $16, %rsp
    iretq

/* A CPU fault inside the VM returns here instead of to the faulting
   instruction; it is turned into a Python exception. */
.global fault_trampoline
fault_trampoline:
    andq $-16, %rsp
    call rust_fault_raise
    ud2
"#,
    options(att_syntax)
);

global_asm!(include_str!(concat!(env!("OUT_DIR"), "/isr_stubs.s")), options(att_syntax));
