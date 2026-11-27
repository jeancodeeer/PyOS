//! ARM64 bring-up. BOOTAA64.EFI (boot/aarch64-efi) jumps to `_start` with
//! x0 = BootInfo, interrupts masked, at EL2 or EL1, MMU on (the firmware's).
//!
//! `_start` cleans the data caches to memory, drops to EL1 if needed, turns
//! the MMU off, switches the FP/SIMD unit on and calls `kmain_arm`, which
//! builds our own identity map (RAM cacheable, everything else device
//! memory), reads the ACPI tables (GIC, PCIe, UART, PSCI), starts the timer
//! and hands over to the same Python start-up as on PCs.
//! Also the exception vectors and the thread switch.

use crate::{info_set, klog, I};
use core::arch::{asm, global_asm};
use core::ptr::{read_unaligned as rdu, read_volatile as rdv, write_volatile as wrv};

#[repr(C)]
pub struct BootInfo {
    magic: u64,
    kernel_base: u64,
    kernel_end: u64,
    initrd_start: u64,
    initrd_end: u64,
    fb_addr: u64,
    fb_width: u64,
    fb_height: u64,
    fb_pitch: u64,
    fb_format: u64,
    rsdp: u64,
    epoch: u64,
    mmap: u64,
    mmap_size: u64,
    mmap_desc: u64,
}

global_asm!(
    r#"
.section .text.boot, "ax"
.global _start
_start:
    msr daifset, #0xf
    mov x19, x0
    bl dcache_clean_inval_all          /* memory holds everything: the MMU goes off next */
    mrs x0, CurrentEL
    lsr x0, x0, #2
    cmp x0, #2
    b.ne 1f
    /* EL2 -> EL1 (64-bit), timers usable from EL1, EL1's MMU and caches off */
    mov x0, #(1 << 31)
    msr hcr_el2, x0
    mov x0, #3
    msr cnthctl_el2, x0
    msr cntvoff_el2, xzr
    mrs x0, id_aa64pfr0_el1             /* a GICv3 CPU interface: open it to EL1 */
    ubfx x0, x0, #24, #4
    cbz x0, 4f
    mrs x0, S3_4_C12_C9_5               /* ICC_SRE_EL2 */
    orr x0, x0, #0xf                    /* SRE, DFB, DIB, Enable */
    msr S3_4_C12_C9_5, x0
    isb
    msr S3_4_C12_C11_0, xzr             /* ICH_HCR_EL2 */
4:
    ldr x0, =0x30d00800
    msr sctlr_el1, x0
    mov x0, #0x3c5
    msr spsr_el2, x0
    adr x0, 2f
    msr elr_el2, x0
    eret
1:  mrs x0, sctlr_el1                  /* at EL1: MMU and caches off */
    bic x0, x0, #1
    bic x0, x0, #(1 << 2)
    bic x0, x0, #(1 << 12)
    msr sctlr_el1, x0
    isb
2:  ic iallu
    tlbi vmalle1
    dsb sy
    isb
    mov x0, #(3 << 20)                 /* FP/SIMD: the Python VM uses it */
    msr cpacr_el1, x0
    isb
    adrp x0, boot_stack_top
    add x0, x0, :lo12:boot_stack_top
    mov sp, x0
    adrp x0, exception_vectors
    add x0, x0, :lo12:exception_vectors
    msr vbar_el1, x0
    isb
    mov x0, x19
    bl kmain_arm
3:  wfi
    b 3b

/* clean and invalidate every data cache level by set/way (as Linux's __flush_dcache_all) */
dcache_clean_inval_all:
    mrs x0, clidr_el1
    and x3, x0, #0x07000000
    lsr x3, x3, #23
    cbz x3, 5f
    mov x10, #0
1:  add x2, x10, x10, lsr #1
    lsr x1, x0, x2
    and x1, x1, #7
    cmp x1, #2
    b.lt 4f
    msr csselr_el1, x10
    isb
    mrs x1, ccsidr_el1
    and x2, x1, #7
    add x2, x2, #4
    mov x4, #0x3ff
    and x4, x4, x1, lsr #3
    clz w5, w4
    mov x7, #0x7fff
    and x7, x7, x1, lsr #13
2:  mov x9, x4
3:  lsl x6, x9, x5
    orr x11, x10, x6
    lsl x6, x7, x2
    orr x11, x11, x6
    dc cisw, x11
    subs x9, x9, #1
    b.ge 3b
    subs x7, x7, #1
    b.ge 2b
4:  add x10, x10, #2
    cmp x3, x10
    b.gt 1b
5:  msr csselr_el1, xzr
    dsb sy
    isb
    ret

.global mmu_on
mmu_on:                                /* x0 = TTBR0, x1 = TCR, x2 = MAIR */
    msr mair_el1, x2
    msr tcr_el1, x1
    msr ttbr0_el1, x0
    isb
    tlbi vmalle1
    dsb ish
    isb
    mrs x3, sctlr_el1
    mov x4, #((1 << 0) | (1 << 2) | (1 << 12))
    orr x3, x3, x4
    bic x3, x3, #(1 << 1)              /* no alignment checks */
    bic x3, x3, #(1 << 19)             /* no write-implies-never-execute */
    msr sctlr_el1, x3
    isb
    ret

/* ---- exceptions: every one saves the whole CPU state (800 bytes) ---- */
.macro VEC kind
    .balign 0x80
    sub sp, sp, #800
    stp x0, x1, [sp, #0]
    mov x0, #\kind
    b exc_common
.endm

.section .text.vectors, "ax"
.balign 0x800
.global exception_vectors
exception_vectors:
    VEC 0
    VEC 1
    VEC 2
    VEC 3
    VEC 0
    VEC 1
    VEC 2
    VEC 3
    VEC 4
    VEC 4
    VEC 4
    VEC 4
    VEC 4
    VEC 4
    VEC 4
    VEC 4

exc_common:
    stp x2, x3, [sp, #16]
    stp x4, x5, [sp, #32]
    stp x6, x7, [sp, #48]
    stp x8, x9, [sp, #64]
    stp x10, x11, [sp, #80]
    stp x12, x13, [sp, #96]
    stp x14, x15, [sp, #112]
    stp x16, x17, [sp, #128]
    stp x18, x19, [sp, #144]
    stp x20, x21, [sp, #160]
    stp x22, x23, [sp, #176]
    stp x24, x25, [sp, #192]
    stp x26, x27, [sp, #208]
    stp x28, x29, [sp, #224]
    str x30, [sp, #240]
    mrs x1, elr_el1
    mrs x2, spsr_el1
    stp x1, x2, [sp, #248]
    str x0, [sp, #264]
    add x1, sp, #272
    stp q0, q1, [x1, #0]
    stp q2, q3, [x1, #32]
    stp q4, q5, [x1, #64]
    stp q6, q7, [x1, #96]
    stp q8, q9, [x1, #128]
    stp q10, q11, [x1, #160]
    stp q12, q13, [x1, #192]
    stp q14, q15, [x1, #224]
    stp q16, q17, [x1, #256]
    stp q18, q19, [x1, #288]
    stp q20, q21, [x1, #320]
    stp q22, q23, [x1, #352]
    stp q24, q25, [x1, #384]
    stp q26, q27, [x1, #416]
    stp q28, q29, [x1, #448]
    stp q30, q31, [x1, #480]
    mrs x2, fpsr
    mrs x3, fpcr
    add x1, x1, #512
    stp x2, x3, [x1]
    mov x0, sp
    bl arm_exception
    add x1, sp, #272
    add x4, x1, #512
    ldp x2, x3, [x4]
    msr fpsr, x2
    msr fpcr, x3
    ldp q0, q1, [x1, #0]
    ldp q2, q3, [x1, #32]
    ldp q4, q5, [x1, #64]
    ldp q6, q7, [x1, #96]
    ldp q8, q9, [x1, #128]
    ldp q10, q11, [x1, #160]
    ldp q12, q13, [x1, #192]
    ldp q14, q15, [x1, #224]
    ldp q16, q17, [x1, #256]
    ldp q18, q19, [x1, #288]
    ldp q20, q21, [x1, #320]
    ldp q22, q23, [x1, #352]
    ldp q24, q25, [x1, #384]
    ldp q26, q27, [x1, #416]
    ldp q28, q29, [x1, #448]
    ldp q30, q31, [x1, #480]
    ldp x1, x2, [sp, #248]
    msr elr_el1, x1
    msr spsr_el1, x2
    ldp x2, x3, [sp, #16]
    ldp x4, x5, [sp, #32]
    ldp x6, x7, [sp, #48]
    ldp x8, x9, [sp, #64]
    ldp x10, x11, [sp, #80]
    ldp x12, x13, [sp, #96]
    ldp x14, x15, [sp, #112]
    ldp x16, x17, [sp, #128]
    ldp x18, x19, [sp, #144]
    ldp x20, x21, [sp, #160]
    ldp x22, x23, [sp, #176]
    ldp x24, x25, [sp, #192]
    ldp x26, x27, [sp, #208]
    ldp x28, x29, [sp, #224]
    ldr x30, [sp, #240]
    ldp x0, x1, [sp, #0]
    add sp, sp, #800
    eret

.global fault_trampoline
fault_trampoline:
    bl rust_fault_raise
    brk #0

.section .bss.stack, "aw", %nobits
.balign 4096
.global boot_stack
boot_stack: .skip 0x80000
.global boot_stack_top
boot_stack_top:
"#
);

extern "C" {
    fn mmu_on(ttbr0: u64, tcr: u64, mair: u64);
}

// ---- the identity map: 1 TiB, 2 MiB blocks below 4 GiB, 1 GiB blocks above ----

#[repr(C, align(4096))]
struct Table([u64; 512]);
static mut L0: Table = Table([0; 512]);
static mut L1: [Table; 2] = [Table([0; 512]), Table([0; 512])];
static mut L2: [Table; 4] = [Table([0; 512]), Table([0; 512]), Table([0; 512]), Table([0; 512])];

const DEVICE: u64 = (0 << 2) | (1 << 10) | (1 << 53) | (1 << 54) | 1;      // AttrIndx 0, AF, PXN, UXN, block
const NORMAL: u64 = (1 << 2) | (3 << 8) | (1 << 10) | 1;                     // AttrIndx 1, inner shareable, AF
const UNCACHED: u64 = (2 << 2) | (3 << 8) | (1 << 10) | 1;                   // AttrIndx 2: the framebuffer
const MAIR: u64 = 0x04 | (0xFF << 8) | (0x44 << 16);                         // device nGnRE, normal WB, normal NC

/// UEFI memory types that are RAM (cacheable): loader/boot/runtime code and data,
/// conventional, ACPI reclaim/NVS, persistent.
fn is_ram(kind: u32) -> bool {
    matches!(kind, 1..=7 | 9 | 10 | 14)
}

/// UEFI memory types free for us after ExitBootServices (loader data holds the
/// kernel, the boot archive and this BootInfo: not free).
fn is_free(kind: u32) -> bool {
    matches!(kind, 1 | 3 | 4 | 7)
}

unsafe fn each_desc(bi: &BootInfo, mut f: impl FnMut(u32, u64, u64)) {
    if bi.mmap == 0 || bi.mmap_desc < 32 {
        return;
    }
    let mut p = bi.mmap;
    while p + bi.mmap_desc <= bi.mmap + bi.mmap_size {
        let kind = rdv(p as *const u32);
        let start = rdv((p + 8) as *const u64);
        let pages = rdv((p + 24) as *const u64);
        f(kind, start, start + pages * 4096);
        p += bi.mmap_desc;
    }
}

unsafe fn build_map(bi: &BootInfo) -> u64 {
    let ram = |s: u64, e: u64| -> bool {
        let mut hit = false;
        each_desc(bi, |k, a, b| {
            if is_ram(k) && a < e && b > s {
                hit = true;
            }
        });
        hit
    };
    let fb = |s: u64, e: u64| bi.fb_addr != 0 && s < bi.fb_addr + bi.fb_pitch * bi.fb_height && e > bi.fb_addr;
    let l0 = &mut *core::ptr::addr_of_mut!(L0);
    let l1 = &mut *core::ptr::addr_of_mut!(L1);
    let l2 = &mut *core::ptr::addr_of_mut!(L2);
    for t in 0..2 {
        wrv(&mut l0.0[t], (&l1[t] as *const Table as u64) | 3);
        for i in 0..512 {
            let gb = (t as u64 * 512 + i as u64) << 30;
            let entry = if t == 0 && i < 4 {
                for j in 0..512 {
                    let s = gb + ((j as u64) << 21);
                    let e = s + (1 << 21);
                    let attr = if fb(s, e) { UNCACHED } else if ram(s, e) { NORMAL } else { DEVICE };
                    wrv(&mut l2[i].0[j], s | attr);
                }
                (&l2[i] as *const Table as u64) | 3
            } else {
                let e = gb + (1 << 30);
                gb | if fb(gb, e) { UNCACHED } else if ram(gb, e) { NORMAL } else { DEVICE }
            };
            wrv(&mut l1[t].0[i], entry);
        }
    }
    core::ptr::addr_of!(L0) as u64
}

// ---- ACPI: just enough to find the hardware ----

pub struct Hw {
    pub gicd: u64,
    pub gicc: u64,
    pub gic_version: u8,
    pub gicr: u64,       // GICv3: the redistributors

    pub ecam: u64,
    pub ecam_bus0: u8,
    pub ecam_bus1: u8,
    pub uart: u64,
    pub psci: u64,       // 0 none, 1 SMC, 2 HVC
    pub timer_irq: u32,
}

pub static mut HW: Hw = Hw { gicd: 0, gicc: 0, gic_version: 2, gicr: 0, ecam: 0, ecam_bus0: 0, ecam_bus1: 255,
                             uart: 0x0900_0000, psci: 2, timer_irq: 27 };

unsafe fn acpi(rsdp: u64) {
    let hw = &mut *core::ptr::addr_of_mut!(HW);
    if rsdp == 0 || rdu(rsdp as *const [u8; 8]) != *b"RSD PTR " {
        klog!("acpi: no tables; assuming QEMU virt");
        hw.gicd = 0x0800_0000;
        hw.gicc = 0x0801_0000;
        hw.ecam = 0x40_1000_0000;
        return;
    }
    let xsdt = rdu((rsdp + 24) as *const u64);
    let n = (rdu((xsdt + 4) as *const u32) as u64 - 36) / 8;
    for i in 0..n {
        let t = rdu((xsdt + 36 + i * 8) as *const u64);
        let sig = rdu(t as *const [u8; 4]);
        let len = rdu((t + 4) as *const u32) as u64;
        match &sig {
            b"APIC" => {
                let mut p = t + 44;
                while p + 2 <= t + len {
                    let (kind, l) = (rdu(p as *const u8), rdu((p + 1) as *const u8) as u64);
                    if l == 0 {
                        break;
                    }
                    if kind == 0x0B && hw.gicc == 0 {
                        hw.gicc = rdu((p + 32) as *const u64);
                        if l >= 76 && hw.gicr == 0 {
                            hw.gicr = rdu((p + 68) as *const u64);     // GICR base of this CPU (GICv3)
                        }
                    } else if kind == 0x0C {
                        hw.gicd = rdu((p + 8) as *const u64);
                        hw.gic_version = rdu((p + 20) as *const u8);
                    } else if kind == 0x0E {
                        hw.gicr = rdu((p + 4) as *const u64);          // GICR discovery range
                    }
                    p += l;
                }
            }
            b"MCFG" if len >= 60 => {
                hw.ecam = rdu((t + 44) as *const u64);
                hw.ecam_bus0 = rdu((t + 54) as *const u8);
                hw.ecam_bus1 = rdu((t + 55) as *const u8);
            }
            b"SPCR" if len >= 52 => {
                let a = rdu((t + 44) as *const u64);
                if a != 0 {
                    hw.uart = a;
                }
            }
            b"FACP" if len >= 131 => {
                let flags = rdu((t + 129) as *const u16);
                hw.psci = if flags & 1 == 0 { 0 } else if flags & 2 != 0 { 2 } else { 1 };
            }
            b"GTDT" if len >= 72 => {
                let v = rdu((t + 64) as *const u32);
                if v != 0 {
                    hw.timer_irq = v;
                }
            }
            _ => {}
        }
    }
}

/// QEMU virt's PCI I/O window (where x86-style port I/O lands on this machine).
const PIO_WINDOW: u64 = 0x3eff_0000;

#[no_mangle]
pub unsafe extern "C" fn kmain_arm(bi: &BootInfo) -> ! {
    // 1. our own page tables, so RAM is cached and devices are not
    let mut pa: u64;
    asm!("mrs {}, id_aa64mmfr0_el1", out(reg) pa);
    let ips = (pa & 7).min(5);
    let tcr = 16 | (1 << 8) | (1 << 10) | (3 << 12) | (1 << 23) | (ips << 32);   // T0SZ 16, WB walks, 4K, no TTBR1
    let root = build_map(bi);
    mmu_on(root, tcr, MAIR);
    pa = 0;
    let _ = pa;

    // 2. the hardware, from ACPI
    acpi(bi.rsdp);
    crate::serial::init((*core::ptr::addr_of!(HW)).uart);
    klog!("\nPyKernel: rust layer up (ARM64)");
    let hw = &*core::ptr::addr_of!(HW);
    klog!("acpi: GICv{} dist {:#x} cpu {:#x} redist {:#x}, PCIe {:#x}, UART {:#x}, PSCI {}, timer irq {}",
          hw.gic_version, hw.gicd, hw.gicc, hw.gicr, hw.ecam, hw.uart, ["none", "smc", "hvc"][hw.psci as usize], hw.timer_irq);
    crate::cpu::set_pci(hw.ecam, hw.ecam_bus0, hw.ecam_bus1, PIO_WINDOW);
    crate::interrupts::init(hw);

    // 3. what Python learns from _kernel.info()
    extern "C" {
        static __kernel_end: u8;
        static boot_stack: u8;
        static boot_stack_top: u8;
    }
    info_set(I::KSTART, bi.kernel_base);
    info_set(I::KEND, core::ptr::addr_of!(__kernel_end) as u64);
    info_set(I::STACK_BASE, core::ptr::addr_of!(boot_stack) as u64);
    info_set(I::STACK_TOP, core::ptr::addr_of!(boot_stack_top) as u64);
    info_set(I::INITRD_START, bi.initrd_start);
    info_set(I::INITRD_END, bi.initrd_end);
    info_set(I::ARCH, 1);
    info_set(I::FB_ADDR, bi.fb_addr);
    info_set(I::FB_WIDTH, bi.fb_width);
    info_set(I::FB_HEIGHT, bi.fb_height);
    info_set(I::FB_PITCH, bi.fb_pitch);
    info_set(I::FB_FORMAT, bi.fb_format);
    info_set(I::RSDP, bi.rsdp);
    info_set(I::EPOCH, bi.epoch);
    info_set(I::ECAM, hw.ecam);
    info_set(I::PIO, PIO_WINDOW);
    info_set(I::PSCI, hw.psci);
    let freq: u64;
    asm!("mrs {}, cntfrq_el0", out(reg) freq);
    info_set(I::TIMER_HZ, freq);
    info_set(I::MMAP, bi.mmap);
    info_set(I::MMAP_SIZE, bi.mmap_size);
    info_set(I::MMAP_DESC, bi.mmap_desc);
    info_set(I::TIMER_IRQ, hw.timer_irq as u64);

    // 4. memory: the free RAM regions, then the same plan as on PCs
    let mut regions: [(u64, u64); 32] = [(0, 0); 32];
    let mut n = 0;
    let mut total = 0;
    let floor = bi.kernel_end.max(bi.initrd_end);
    each_desc(bi, |k, s, e| {
        if is_free(k) && n < 32 {
            // merge with the previous region when they touch
            if n > 0 && regions[n - 1].1 == s {
                regions[n - 1].1 = e;
            } else {
                regions[n] = (s, e);
                n += 1;
            }
            total += e - s;
        }
    });
    let _ = floor;
    crate::plan_memory(&mut regions, n, total);
    klog!("PyKernel: {} MiB of RAM, python heap {:#x}..{:#x}", total >> 20,
          crate::rk_info(I::HEAP_START as u32), crate::rk_info(I::HEAP_END as u32));
    crate::interrupts::start_timer(100);
    crate::run()
}
