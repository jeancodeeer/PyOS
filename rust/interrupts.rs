//! IDT and the single interrupt dispatcher.
//!
//! Rust's whole job here is mechanism: count the interrupt and, if Python
//! registered a handler for that vector, queue it on the VM scheduler. The
//! interrupt controller, EOI, masking and every device are Python's business.
//! CPU faults raised while the VM is running become Python exceptions.

use crate::{cpu, klog};
use core::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering::Relaxed};

#[repr(C)]
pub struct Frame {
    pub r15: u64, pub r14: u64, pub r13: u64, pub r12: u64,
    pub r11: u64, pub r10: u64, pub r9: u64, pub r8: u64,
    pub rdi: u64, pub rsi: u64, pub rbp: u64, pub rbx: u64,
    pub rdx: u64, pub rcx: u64, pub rax: u64,
    pub vector: u64, pub err: u64,
    pub rip: u64, pub cs: u64, pub rflags: u64, pub rsp: u64, pub ss: u64,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct Gate {
    off_lo: u16,
    sel: u16,
    ist: u8,
    attr: u8,
    off_mid: u16,
    off_hi: u32,
    zero: u32,
}

#[repr(C, packed)]
struct Idtr {
    limit: u16,
    base: u64,
}

static mut IDT: [Gate; 256] = [Gate { off_lo: 0, sel: 0, ist: 0, attr: 0, off_mid: 0, off_hi: 0, zero: 0 }; 256];

static COUNT: [AtomicU64; 256] = [const { AtomicU64::new(0) }; 256];
static ARMED: [AtomicBool; 256] = [const { AtomicBool::new(false) }; 256];
static PENDING: [AtomicBool; 256] = [const { AtomicBool::new(false) }; 256];
static DROPPED: AtomicU64 = AtomicU64::new(0);
pub static IN_VM: AtomicBool = AtomicBool::new(false);
static FAULT: [AtomicU64; 4] = [const { AtomicU64::new(0) }; 4];

extern "C" {
    static isr_stub_table: [u64; 256];
    fn fault_trampoline();
    fn mpk_schedule_irq(vector: u32) -> bool;
    fn mpk_raise_fault(vector: u64, err: u64, rip: u64, cr2: u64) -> !;
}

pub fn init() {
    unsafe {
        let idt = &mut *core::ptr::addr_of_mut!(IDT);
        for (v, gate) in idt.iter_mut().enumerate() {
            let h = isr_stub_table[v];
            *gate = Gate {
                off_lo: h as u16,
                sel: 0x08,
                ist: 0,
                attr: 0x8E, // present, ring 0, interrupt gate
                off_mid: (h >> 16) as u16,
                off_hi: (h >> 32) as u32,
                zero: 0,
            };
        }
        let idtr = Idtr { limit: (core::mem::size_of::<[Gate; 256]>() - 1) as u16, base: idt.as_ptr() as u64 };
        core::arch::asm!("lidt [{}]", in(reg) &idtr as *const Idtr, options(readonly, nostack));
    }
}

pub fn idt_addr() -> u64 {
    core::ptr::addr_of!(IDT) as u64
}

/// Forget every Python handler (used on soft reboot).
pub fn reset() {
    for v in 0..256 {
        ARMED[v].store(false, Relaxed);
        PENDING[v].store(false, Relaxed);
    }
    for s in 0..FIFOS {
        FIFO_VEC[s].store(NONE, Relaxed);
    }
}

// ---- byte FIFOs: read a device's data port the moment it interrupts ----
//
// Some devices (the PS/2 controller, a UART) hold only a few bytes and drop
// the rest if nobody reads them in time; the Python handler can run much
// later (GC, a busy thread). Python names the ports ("while status & mask:
// read data") and this copies the bytes into a ring at interrupt time.

const FIFOS: usize = 4;
const FIFO_LEN: usize = 1024;
const NONE: u32 = 0xFFFF_FFFF;
static FIFO_VEC: [core::sync::atomic::AtomicU32; FIFOS] = [const { core::sync::atomic::AtomicU32::new(NONE) }; FIFOS];
static mut FIFO_CFG: [(u16, u8, u8, u16); FIFOS] = [(0, 0, 0, 0); FIFOS];
static mut FIFO_BUF: [[u8; FIFO_LEN]; FIFOS] = [[0; FIFO_LEN]; FIFOS];
static FIFO_HEAD: [AtomicUsize; FIFOS] = [const { AtomicUsize::new(0) }; FIFOS];
static FIFO_TAIL: [AtomicUsize; FIFOS] = [const { AtomicUsize::new(0) }; FIFOS];
static FIFO_LOST: AtomicU64 = AtomicU64::new(0);

fn fifo_drain(v: usize) {
    for s in 0..FIFOS {
        if FIFO_VEC[s].load(Relaxed) != v as u32 {
            continue;
        }
        let (status, mask, value, data) = unsafe { (*core::ptr::addr_of!(FIFO_CFG))[s] };
        for _ in 0..64 {
            if unsafe { cpu::inb(status) } & mask != value {
                break;
            }
            let b = unsafe { cpu::inb(data) };
            let h = FIFO_HEAD[s].load(Relaxed);
            let next = (h + 1) % FIFO_LEN;
            if next == FIFO_TAIL[s].load(Relaxed) {
                FIFO_LOST.fetch_add(1, Relaxed);
            } else {
                unsafe { (*core::ptr::addr_of_mut!(FIFO_BUF))[s][h] = b };
                FIFO_HEAD[s].store(next, Relaxed);
            }
        }
    }
}

/// Capture bytes for `vector`: on each interrupt, while
/// inb(status) & mask == value, queue inb(data). mask 0 removes the FIFO.
/// Returns false if all are in use.
#[no_mangle]
pub extern "C" fn rk_irq_fifo(vector: u32, status: u16, mask: u8, value: u8, data: u16) -> bool {
    let flags = cpu::rk_irq_save();
    let mut slot = None;
    for s in 0..FIFOS {
        let cur = FIFO_VEC[s].load(Relaxed);
        if cur == vector {
            slot = Some(s);
            break;
        }
        if cur == NONE && slot.is_none() {
            slot = Some(s);
        }
    }
    let ok = match slot {
        Some(s) => {
            FIFO_VEC[s].store(NONE, Relaxed);
            if mask != 0 {
                unsafe { (*core::ptr::addr_of_mut!(FIFO_CFG))[s] = (status, mask, value, data) };
                FIFO_TAIL[s].store(FIFO_HEAD[s].load(Relaxed), Relaxed);
                FIFO_VEC[s].store(vector, Relaxed);
            }
            true
        }
        None => mask == 0,
    };
    cpu::rk_irq_restore(flags);
    ok
}

/// Copy up to `len` queued bytes of `vector`'s FIFO into `out`; returns how many.
#[no_mangle]
pub extern "C" fn rk_irq_fifo_read(vector: u32, out: *mut u8, len: usize) -> usize {
    for s in 0..FIFOS {
        if FIFO_VEC[s].load(Relaxed) != vector {
            continue;
        }
        let mut n = 0;
        while n < len {
            let t = FIFO_TAIL[s].load(Relaxed);
            if t == FIFO_HEAD[s].load(Relaxed) {
                break;
            }
            unsafe { *out.add(n) = (*core::ptr::addr_of!(FIFO_BUF))[s][t] };
            FIFO_TAIL[s].store((t + 1) % FIFO_LEN, Relaxed);
            n += 1;
        }
        return n;
    }
    0
}

#[no_mangle]
pub extern "C" fn rk_irq_fifo_lost() -> u64 {
    FIFO_LOST.load(Relaxed)
}

#[no_mangle]
extern "C" fn rust_isr(f: &mut Frame) {
    let v = f.vector as usize & 0xFF;
    COUNT[v].fetch_add(1, Relaxed);
    if v < 32 && !matches!(v, 1 | 2 | 3) {
        return fault(f);
    }
    fifo_drain(v);
    if ARMED[v].load(Relaxed) && !PENDING[v].swap(true, Relaxed) {
        if !unsafe { mpk_schedule_irq(v as u32) } {
            PENDING[v].store(false, Relaxed);
            DROPPED.fetch_add(1, Relaxed);
        }
    }
    if v >= 32 {
        // Wake sleeping threads; on the tick vector this may also preempt,
        // in which case it returns only when this thread is scheduled again.
        unsafe { crate::sched::on_interrupt(v as u32) };
    }
}

fn fault(f: &mut Frame) {
    let cr2 = unsafe { cpu::rk_read_cr(2) };
    let recoverable = IN_VM.load(Relaxed)
        && !matches!(f.vector, 8 | 18)
        && f.rip != fault_trampoline as *const () as u64;
    if !recoverable {
        klog!("\n*** CPU exception {} err={:#x} rip={:#x} cr2={:#x}", f.vector, f.err, f.rip, cr2);
        klog!("    rsp={:#x} rflags={:#x} rax={:#x} rbx={:#x} rcx={:#x} rdx={:#x}", f.rsp, f.rflags, f.rax, f.rbx, f.rcx, f.rdx);
        klog!("    rsi={:#x} rdi={:#x} rbp={:#x}  -- halted", f.rsi, f.rdi, f.rbp);
        cpu::halt_forever();
    }
    FAULT[0].store(f.vector, Relaxed);
    FAULT[1].store(f.err, Relaxed);
    FAULT[2].store(f.rip, Relaxed);
    FAULT[3].store(cr2, Relaxed);
    f.rip = fault_trampoline as *const () as u64;
}

#[no_mangle]
extern "C" fn rust_fault_raise() -> ! {
    unsafe { mpk_raise_fault(FAULT[0].load(Relaxed), FAULT[1].load(Relaxed), FAULT[2].load(Relaxed), FAULT[3].load(Relaxed)) }
}

// ---- interface used by the Python binding glue ----

#[no_mangle]
pub extern "C" fn rk_irq_arm(vector: u32, on: bool) {
    ARMED[vector as usize & 0xFF].store(on, Relaxed);
}
#[no_mangle]
pub extern "C" fn rk_irq_ack(vector: u32) {
    PENDING[vector as usize & 0xFF].store(false, Relaxed);
}
#[no_mangle]
pub extern "C" fn rk_irq_count(vector: u32) -> u64 {
    COUNT[vector as usize & 0xFF].load(Relaxed)
}
#[no_mangle]
pub extern "C" fn rk_irq_dropped() -> u64 {
    DROPPED.load(Relaxed)
}
