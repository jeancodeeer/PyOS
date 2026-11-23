//! Raw CPU primitives. Each one is the smallest thing Python cannot do for
//! itself; all policy built on them lives in Python (`/lib/kernel`).

use core::arch::asm;

#[no_mangle]
pub unsafe extern "C" fn rk_inb(port: u16) -> u8 {
    let v: u8;
    asm!("in al, dx", in("dx") port, out("al") v, options(nomem, nostack, preserves_flags));
    v
}
#[no_mangle]
pub unsafe extern "C" fn rk_inw(port: u16) -> u16 {
    let v: u16;
    asm!("in ax, dx", in("dx") port, out("ax") v, options(nomem, nostack, preserves_flags));
    v
}
#[no_mangle]
pub unsafe extern "C" fn rk_inl(port: u16) -> u32 {
    let v: u32;
    asm!("in eax, dx", in("dx") port, out("eax") v, options(nomem, nostack, preserves_flags));
    v
}
#[no_mangle]
pub unsafe extern "C" fn rk_outb(port: u16, v: u8) {
    asm!("out dx, al", in("dx") port, in("al") v, options(nomem, nostack, preserves_flags));
}
#[no_mangle]
pub unsafe extern "C" fn rk_outw(port: u16, v: u16) {
    asm!("out dx, ax", in("dx") port, in("ax") v, options(nomem, nostack, preserves_flags));
}
#[no_mangle]
pub unsafe extern "C" fn rk_outl(port: u16, v: u32) {
    asm!("out dx, eax", in("dx") port, in("eax") v, options(nomem, nostack, preserves_flags));
}
/// Block transfer of 16-bit words (disk sectors): `rep insw` / `rep outsw`.
#[no_mangle]
pub unsafe extern "C" fn rk_insw(port: u16, buf: *mut u16, words: usize) {
    asm!("rep insw", in("dx") port, inout("rdi") buf => _, inout("rcx") words => _, options(nostack));
}
#[no_mangle]
pub unsafe extern "C" fn rk_outsw(port: u16, buf: *const u16, words: usize) {
    asm!("rep outsw", in("dx") port, inout("rsi") buf => _, inout("rcx") words => _, options(nostack, readonly));
}
pub use {rk_inb as inb, rk_outb as outb};

/// Disable interrupts; returns the previous RFLAGS (bit 9 = were enabled).
#[no_mangle]
pub extern "C" fn rk_irq_save() -> u64 {
    let f: u64;
    unsafe { asm!("pushfq", "pop {}", "cli", out(reg) f) };
    f
}
#[no_mangle]
pub extern "C" fn rk_irq_restore(flags: u64) {
    if flags & 0x200 != 0 {
        unsafe { asm!("sti", options(nomem, nostack)) };
    }
}
#[no_mangle]
pub extern "C" fn rk_cli() {
    unsafe { asm!("cli", options(nomem, nostack)) };
}
#[no_mangle]
pub extern "C" fn rk_sti() {
    unsafe { asm!("sti", options(nomem, nostack)) };
}
/// Atomically enable interrupts and sleep until the next one.
#[no_mangle]
pub extern "C" fn rk_sti_hlt() {
    unsafe { asm!("sti", "hlt", options(nomem, nostack)) };
}
#[no_mangle]
pub extern "C" fn rk_hlt() {
    unsafe { asm!("hlt", options(nomem, nostack)) };
}

#[no_mangle]
pub unsafe extern "C" fn rk_rdmsr(msr: u32) -> u64 {
    let (lo, hi): (u32, u32);
    asm!("rdmsr", in("ecx") msr, out("eax") lo, out("edx") hi, options(nomem, nostack));
    (hi as u64) << 32 | lo as u64
}
#[no_mangle]
pub unsafe extern "C" fn rk_wrmsr(msr: u32, v: u64) {
    asm!("wrmsr", in("ecx") msr, in("eax") v as u32, in("edx") (v >> 32) as u32, options(nomem, nostack));
}
#[no_mangle]
pub unsafe extern "C" fn rk_cpuid(leaf: u32, sub: u32, out: *mut u32) {
    let r = core::arch::x86_64::__cpuid_count(leaf, sub);
    *out = r.eax;
    *out.add(1) = r.ebx;
    *out.add(2) = r.ecx;
    *out.add(3) = r.edx;
}
#[no_mangle]
pub extern "C" fn rk_rdtsc() -> u64 {
    let (lo, hi): (u32, u32);
    unsafe { asm!("rdtsc", out("eax") lo, out("edx") hi, options(nomem, nostack)) };
    (hi as u64) << 32 | lo as u64
}
#[no_mangle]
pub unsafe extern "C" fn rk_read_cr(n: u32) -> u64 {
    let v: u64;
    match n {
        0 => asm!("mov {}, cr0", out(reg) v, options(nomem, nostack)),
        2 => asm!("mov {}, cr2", out(reg) v, options(nomem, nostack)),
        3 => asm!("mov {}, cr3", out(reg) v, options(nomem, nostack)),
        4 => asm!("mov {}, cr4", out(reg) v, options(nomem, nostack)),
        _ => asm!("mov {}, cr8", out(reg) v, options(nomem, nostack)),
    }
    v
}
#[no_mangle]
pub unsafe extern "C" fn rk_write_cr(n: u32, v: u64) {
    match n {
        0 => asm!("mov cr0, {}", in(reg) v, options(nostack)),
        2 => asm!("mov cr2, {}", in(reg) v, options(nostack)),
        3 => asm!("mov cr3, {}", in(reg) v, options(nostack)),
        4 => asm!("mov cr4, {}", in(reg) v, options(nostack)),
        _ => asm!("mov cr8, {}", in(reg) v, options(nostack)),
    }
}
#[no_mangle]
pub unsafe extern "C" fn rk_invlpg(addr: u64) {
    asm!("invlpg [{}]", in(reg) addr, options(nostack));
}

/// Call machine code at `addr` with up to six integer arguments. This is the
/// escape hatch: anything missing from this file can be assembled into a
/// bytearray from Python and called.
#[no_mangle]
pub unsafe extern "C" fn rk_call(addr: u64, a: u64, b: u64, c: u64, d: u64, e: u64, f: u64) -> u64 {
    let func: extern "C" fn(u64, u64, u64, u64, u64, u64) -> u64 = core::mem::transmute(addr);
    func(a, b, c, d, e, f)
}

pub fn halt_forever() -> ! {
    loop {
        unsafe { asm!("cli", "hlt", options(nomem, nostack)) };
    }
}
