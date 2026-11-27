//! Exceptions and interrupts on ARM64: the GIC (v2) and the generic timer.
//!
//! As on PCs, Rust only counts an interrupt and queues the Python handler
//! registered for it; the "vector" Python sees is the GIC interrupt number
//! (the timer is 27 on most machines; PCI lines are 32 and up).
//! Unlike the PC's PIC, the GIC is programmed here: arming a vector from
//! Python enables its line, and a device line stays masked from the moment
//! it fires until Python has run its handler (irq_ack), so a level-triggered
//! device cannot flood the CPU.
//! Faults while the VM runs become Python exceptions, as on PCs.

use crate::{boot::Hw, klog};
use core::ptr::{read_volatile as rd, write_volatile as wr};
use core::sync::atomic::{AtomicBool, AtomicU64, Ordering::Relaxed};

#[repr(C)]
pub struct Frame {
    pub x: [u64; 31],
    pub elr: u64,
    pub spsr: u64,
    pub kind: u64,
    // q0-q31, fpsr, fpcr follow (only the assembly touches them)
}

const N: usize = 256;
static COUNT: [AtomicU64; N] = [const { AtomicU64::new(0) }; N];
static ARMED: [AtomicBool; N] = [const { AtomicBool::new(false) }; N];
static PENDING: [AtomicBool; N] = [const { AtomicBool::new(false) }; N];
static DROPPED: AtomicU64 = AtomicU64::new(0);
pub static IN_VM: AtomicBool = AtomicBool::new(false);
static FAULT: [AtomicU64; 4] = [const { AtomicU64::new(0) }; 4];

static mut GICD: u64 = 0;
static mut GICC: u64 = 0;
static mut TIMER_IRQ: u32 = 27;
static mut TIMER_STEP: u64 = 0;

extern "C" {
    fn fault_trampoline();
    fn mpk_schedule_irq(vector: u32) -> bool;
    fn mpk_raise_fault(vector: u64, err: u64, rip: u64, cr2: u64) -> !;
}

unsafe fn d32(off: u64) -> *mut u32 {
    (GICD + off) as *mut u32
}
unsafe fn c32(off: u64) -> *mut u32 {
    (GICC + off) as *mut u32
}

unsafe fn line(id: u32, on: bool) {
    if GICD == 0 || id as usize >= N {
        return;
    }
    let reg = if on { 0x100 } else { 0x180 };
    wr(d32(reg + (id as u64 / 32) * 4), 1 << (id % 32));
}

pub fn init(hw: &Hw) {
    unsafe {
        if hw.gic_version > 2 {
            klog!("irq: GICv{} is not supported yet; no interrupts (polling only)", hw.gic_version);
            return;
        }
        GICD = hw.gicd;
        GICC = hw.gicc;
        TIMER_IRQ = hw.timer_irq;
        if GICD == 0 || GICC == 0 {
            klog!("irq: no GIC found");
            return;
        }
        wr(d32(0), 0);
        let lines = ((rd(d32(4)) & 0x1F) + 1) * 32;
        for i in (0..lines).step_by(32) {
            wr(d32(0x180 + i as u64 / 8), 0xFFFF_FFFF);           // all off
            wr(d32(0x280 + i as u64 / 8), 0xFFFF_FFFF);           // nothing pending
        }
        for i in (0..lines).step_by(4) {
            wr(d32(0x400 + i as u64), 0xA0A0_A0A0);               // one priority for all
            if i >= 32 {
                wr(d32(0x800 + i as u64), 0x0101_0101);           // to CPU 0
            }
        }
        for i in (32..lines).step_by(16) {
            wr(d32(0xC00 + i as u64 / 4), 0);                     // level triggered
        }
        wr(d32(0), 1);
        wr(c32(4), 0xF0);                                         // priority mask
        wr(c32(8), 0);
        wr(c32(0), 1);
    }
}

/// The tick: the virtual generic timer at `hz`.
pub fn start_timer(hz: u64) {
    unsafe {
        let freq: u64;
        core::arch::asm!("mrs {}, cntfrq_el0", out(reg) freq);
        TIMER_STEP = freq / hz;
        core::arch::asm!("msr cntv_tval_el0, {}", "msr cntv_ctl_el0, {}", in(reg) TIMER_STEP, in(reg) 1u64);
        line(TIMER_IRQ, true);
        core::arch::asm!("msr daifclr, #2");
    }
}

/// Forget every Python handler (used on soft reboot).
pub fn reset() {
    for v in 0..N {
        ARMED[v].store(false, Relaxed);
        PENDING[v].store(false, Relaxed);
        if v >= 32 {
            unsafe { line(v as u32, false) };
        }
    }
}

#[no_mangle]
extern "C" fn arm_exception(f: &mut Frame) {
    match f.kind {
        1 => irq(),
        0 => sync(f),
        _ => {
            klog!("\n*** CPU exception kind {} at {:#x} -- halted", f.kind, f.elr);
            crate::cpu::halt_forever();
        }
    }
}

fn irq() {
    unsafe {
        if GICC == 0 {
            return;
        }
        let iar = rd(c32(0x0C));
        let id = iar & 0x3FF;
        if id >= 1020 {
            return;
        }
        if id == TIMER_IRQ {
            core::arch::asm!("msr cntv_tval_el0, {}", in(reg) TIMER_STEP);
        } else if id >= 32 {
            line(id, false);                     // until Python has handled it
        }
        wr(c32(0x10), iar);                      // end of interrupt: others may come
        let v = id as usize;
        if v >= N {
            return;
        }
        COUNT[v].fetch_add(1, Relaxed);
        if ARMED[v].load(Relaxed) && !PENDING[v].swap(true, Relaxed) {
            if !mpk_schedule_irq(v as u32) {
                PENDING[v].store(false, Relaxed);
                DROPPED.fetch_add(1, Relaxed);
                if v >= 32 {
                    line(id, true);
                }
            }
        } else if v >= 32 && !ARMED[v].load(Relaxed) {
            // nobody wants it: leave it off
        }
        crate::sched::on_interrupt(v as u32);
    }
}

fn sync(f: &mut Frame) {
    let (esr, far): (u64, u64);
    unsafe { core::arch::asm!("mrs {}, esr_el1", "mrs {}, far_el1", out(reg) esr, out(reg) far) };
    let recoverable = IN_VM.load(Relaxed) && f.elr != fault_trampoline as *const () as u64;
    if !recoverable {
        klog!("\n*** CPU exception: ESR {:#x} (class {:#x}) at {:#x}, address {:#x} -- halted",
              esr, esr >> 26, f.elr, far);
        klog!("    x0={:#x} x1={:#x} x2={:#x} x29={:#x} x30={:#x}", f.x[0], f.x[1], f.x[2], f.x[29], f.x[30]);
        crate::cpu::halt_forever();
    }
    // vector 14 ("page fault") for data/instruction aborts, 13 for the rest, as Python expects on PCs
    let class = esr >> 26;
    let vector = if matches!(class, 0x20 | 0x21 | 0x24 | 0x25) { 14 } else { 13 };
    FAULT[0].store(vector, Relaxed);
    FAULT[1].store(esr, Relaxed);
    FAULT[2].store(f.elr, Relaxed);
    FAULT[3].store(far, Relaxed);
    f.elr = fault_trampoline as *const () as u64;
}

#[no_mangle]
extern "C" fn rust_fault_raise() -> ! {
    unsafe { mpk_raise_fault(FAULT[0].load(Relaxed), FAULT[1].load(Relaxed), FAULT[2].load(Relaxed), FAULT[3].load(Relaxed)) }
}

// ---- interface used by the Python binding glue ----

#[no_mangle]
pub extern "C" fn rk_irq_arm(vector: u32, on: bool) {
    let v = vector as usize & 0xFF;
    ARMED[v].store(on, Relaxed);
    if v != unsafe { TIMER_IRQ } as usize {
        unsafe { line(v as u32, on) };
    }
}
#[no_mangle]
pub extern "C" fn rk_irq_ack(vector: u32) {
    let v = vector as usize & 0xFF;
    PENDING[v].store(false, Relaxed);
    if v >= 32 && ARMED[v].load(Relaxed) {
        unsafe { line(v as u32, true) };
    }
}
#[no_mangle]
pub extern "C" fn rk_irq_count(vector: u32) -> u64 {
    COUNT[vector as usize & 0xFF].load(Relaxed)
}
#[no_mangle]
pub extern "C" fn rk_irq_dropped() -> u64 {
    DROPPED.load(Relaxed)
}
/// No byte FIFOs on ARM (they read x86 I/O ports at interrupt time).
#[no_mangle]
pub extern "C" fn rk_irq_fifo(_vector: u32, _status: u16, mask: u8, _value: u8, _data: u16) -> bool {
    mask == 0
}
#[no_mangle]
pub extern "C" fn rk_irq_fifo_read(_vector: u32, _out: *mut u8, _len: usize) -> usize {
    0
}
#[no_mangle]
pub extern "C" fn rk_irq_fifo_lost() -> u64 {
    0
}
