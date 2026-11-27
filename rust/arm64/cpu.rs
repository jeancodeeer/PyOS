//! Raw CPU primitives on ARM64, with the same names as on PCs (rust/cpu.rs)
//! so the C glue and Python see one interface.
//!
//! Port I/O does not exist on ARM. Python's drivers use it for two things,
//! and both are kept working here:
//!   - PCI configuration through ports 0xCF8/0xCFC: done on the PCIe ECAM
//!     window from ACPI's MCFG table;
//!   - the I/O BARs of PCI devices (legacy virtio, AC97...): those ports are
//!     memory in the PCI I/O window.
//! The x86-only ones (MSRs, CPUID, control registers) answer 0.

use core::arch::asm;
use core::ptr::{read_volatile as rd, write_volatile as wr};

static mut ECAM: u64 = 0;
static mut BUS0: u8 = 0;
static mut BUS1: u8 = 255;
static mut PIO: u64 = 0;
static mut CF8: u32 = 0;

pub fn set_pci(ecam: u64, bus0: u8, bus1: u8, pio: u64) {
    unsafe {
        ECAM = ecam;
        BUS0 = bus0;
        BUS1 = bus1;
        PIO = pio;
    }
}

/// The ECAM address of the register CF8 selects (plus `byte`), or 0.
unsafe fn cfg_addr(byte: u16) -> u64 {
    let v = CF8;
    let bus = ((v >> 16) & 0xFF) as u8;
    if v & 0x8000_0000 == 0 || ECAM == 0 || bus < BUS0 || bus > BUS1 {
        return 0;
    }
    let dev = ((v >> 11) & 0x1F) as u64;
    let func = ((v >> 8) & 7) as u64;
    ECAM + (((bus - BUS0) as u64) << 20 | dev << 15 | func << 12 | (v & 0xFC) as u64 | (byte & 3) as u64)
}

macro_rules! port_in {
    ($name:ident, $t:ty) => {
        #[no_mangle]
        pub unsafe extern "C" fn $name(port: u16) -> $t {
            if (0xCFC..=0xCFF).contains(&port) {
                let a = cfg_addr(port - 0xCFC);
                return if a == 0 { <$t>::MAX } else { rd(a as *const $t) };
            }
            if port == 0xCF8 {
                return CF8 as $t;
            }
            if PIO == 0 {
                return <$t>::MAX;
            }
            let v = rd((PIO + port as u64) as *const $t);
            asm!("dsb ld");
            v
        }
    };
}
macro_rules! port_out {
    ($name:ident, $t:ty) => {
        #[no_mangle]
        pub unsafe extern "C" fn $name(port: u16, v: $t) {
            if port == 0xCF8 && core::mem::size_of::<$t>() == 4 {
                CF8 = v as u32;
                return;
            }
            if (0xCFC..=0xCFF).contains(&port) {
                let a = cfg_addr(port - 0xCFC);
                if a != 0 {
                    wr(a as *mut $t, v);
                }
                return;
            }
            if PIO != 0 {
                asm!("dsb st");
                wr((PIO + port as u64) as *mut $t, v);
            }
        }
    };
}
port_in!(rk_inb, u8);
port_in!(rk_inw, u16);
port_in!(rk_inl, u32);
port_out!(rk_outb, u8);
port_out!(rk_outw, u16);
port_out!(rk_outl, u32);

#[no_mangle]
pub unsafe extern "C" fn rk_insw(port: u16, buf: *mut u16, words: usize) {
    for i in 0..words {
        *buf.add(i) = rk_inw(port);
    }
}
#[no_mangle]
pub unsafe extern "C" fn rk_outsw(port: u16, buf: *const u16, words: usize) {
    for i in 0..words {
        rk_outw(port, *buf.add(i));
    }
}

/// Mask interrupts; returns 0x200 if they were on (the x86 IF bit, which the
/// C glue and the scheduler test).
#[no_mangle]
pub extern "C" fn rk_irq_save() -> u64 {
    let daif: u64;
    unsafe { asm!("mrs {}, daif", "msr daifset, #2", out(reg) daif, options(nomem, nostack)) };
    if daif & (1 << 7) == 0 { 0x200 } else { 0 }
}
#[no_mangle]
pub extern "C" fn rk_irq_restore(flags: u64) {
    if flags & 0x200 != 0 {
        unsafe { asm!("msr daifclr, #2", options(nomem, nostack)) };
    }
}
#[no_mangle]
pub extern "C" fn rk_cli() {
    unsafe { asm!("msr daifset, #2", options(nomem, nostack)) };
}
#[no_mangle]
pub extern "C" fn rk_sti() {
    unsafe { asm!("msr daifclr, #2", options(nomem, nostack)) };
}
/// Sleep until the next interrupt, then let it in (WFI wakes up even while
/// interrupts are masked, so nothing is lost between the two).
#[no_mangle]
pub extern "C" fn rk_sti_hlt() {
    unsafe { asm!("msr daifset, #2", "wfi", "msr daifclr, #2", "isb", options(nomem, nostack)) };
}
#[no_mangle]
pub extern "C" fn rk_hlt() {
    unsafe { asm!("wfi", options(nomem, nostack)) };
}

#[no_mangle]
pub extern "C" fn rk_rdmsr(_msr: u32) -> u64 {
    0
}
#[no_mangle]
pub extern "C" fn rk_wrmsr(_msr: u32, _v: u64) {}
#[no_mangle]
pub unsafe extern "C" fn rk_cpuid(_leaf: u32, _sub: u32, out: *mut u32) {
    for i in 0..4 {
        *out.add(i) = 0;
    }
}
/// The generic timer's counter (Python calibrates it like the TSC).
#[no_mangle]
pub extern "C" fn rk_rdtsc() -> u64 {
    let v: u64;
    unsafe { asm!("isb", "mrs {}, cntvct_el0", out(reg) v, options(nomem, nostack)) };
    v
}
/// 0: SCTLR_EL1, 2: FAR_EL1, 3: TTBR0_EL1, 4: TCR_EL1, else MIDR_EL1.
#[no_mangle]
pub unsafe extern "C" fn rk_read_cr(n: u32) -> u64 {
    let v: u64;
    match n {
        0 => asm!("mrs {}, sctlr_el1", out(reg) v),
        2 => asm!("mrs {}, far_el1", out(reg) v),
        3 => asm!("mrs {}, ttbr0_el1", out(reg) v),
        4 => asm!("mrs {}, tcr_el1", out(reg) v),
        _ => asm!("mrs {}, midr_el1", out(reg) v),
    }
    v
}
#[no_mangle]
pub extern "C" fn rk_write_cr(_n: u32, _v: u64) {}
#[no_mangle]
pub unsafe extern "C" fn rk_invlpg(addr: u64) {
    asm!("dsb ishst", "tlbi vaae1is, {}", "dsb ish", "isb", in(reg) addr >> 12);
}

/// Call machine code at `addr` (written from Python into a bytearray): make
/// the instruction cache see it first.
#[no_mangle]
pub unsafe extern "C" fn rk_call(addr: u64, a: u64, b: u64, c: u64, d: u64, e: u64, f: u64) -> u64 {
    let mut p = addr & !63;
    while p < addr + 4096 {
        asm!("dc cvau, {0}", "ic ivau, {0}", in(reg) p);
        p += 64;
    }
    asm!("dsb ish", "isb");
    let func: extern "C" fn(u64, u64, u64, u64, u64, u64) -> u64 = core::mem::transmute(addr);
    func(a, b, c, d, e, f)
}

pub fn halt_forever() -> ! {
    loop {
        unsafe { asm!("msr daifset, #2", "wfi", options(nomem, nostack)) };
    }
}
