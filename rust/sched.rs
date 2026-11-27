//! Kernel threads: context switching and the run queue.
//!
//! This is the mechanism behind Python's `_thread` module. A thread is a
//! stack plus a saved stack pointer. Switches happen in three places:
//! the timer interrupt (preemption, when the time slice runs out), a
//! voluntary yield (lock contention), and waiting for an interrupt (sleep,
//! console input). Scheduling is round-robin; the time slice and the tick
//! source are chosen from Python with `_kernel.preempt(vector, ticks)`.
//!
//! Every function here runs with interrupts disabled, which is the only
//! locking this single-CPU scheduler needs.

use crate::cpu;
use core::arch::{asm, global_asm};

pub const MAX_THREADS: usize = 32;

#[derive(Clone, Copy, PartialEq)]
#[repr(u8)]
enum State {
    Free = 0,
    Runnable = 1,
    Waiting = 2, // asleep until the next interrupt
}

#[derive(Clone, Copy)]
struct Thread {
    sp: u64,       // saved stack pointer while switched out
    top: u64,      // highest address of the stack
    tls: u64,      // the VM's per-thread state pointer
    state: State,
    ticks: u64,    // timer ticks spent running
    switches: u64, // times scheduled in
}

const EMPTY: Thread = Thread { sp: 0, top: 0, tls: 0, state: State::Free, ticks: 0, switches: 0 };
static mut THREADS: [Thread; MAX_THREADS] = [EMPTY; MAX_THREADS];
static mut CURRENT: usize = 0;
static mut PREEMPT_VECTOR: u32 = u32::MAX;
static mut SLICE: u32 = 0;
static mut SLICE_LEFT: u32 = 0;

extern "C" {
    static mut mpk_tls: u64; // the VM's "current thread state" (mpy/mpthread.c)
    fn rk_switch_stacks(save_sp: *mut u64, load_sp: u64);
    fn thread_trampoline();
}

#[cfg(target_arch = "x86_64")]
global_asm!(
    r#"
.section .text.sched, "ax"
.code64
.global rk_switch_stacks
rk_switch_stacks:
    pushq %rbp
    pushq %rbx
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    movq %rsp, (%rdi)
    movq %rsi, %rsp
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbx
    popq %rbp
    ret

/* First code a new thread runs: r13 = entry, r12 = argument. */
.global thread_trampoline
thread_trampoline:
    sti
    movq %r12, %rdi
    callq *%r13
    call rk_thread_exit
    ud2
"#,
    options(att_syntax)
);

#[cfg(target_arch = "aarch64")]
global_asm!(
    r#"
.section .text.sched, "ax"
.global rk_switch_stacks
rk_switch_stacks:                      /* x0 = where to save sp, x1 = sp to load */
    sub sp, sp, #160
    stp x19, x20, [sp, #0]
    stp x21, x22, [sp, #16]
    stp x23, x24, [sp, #32]
    stp x25, x26, [sp, #48]
    stp x27, x28, [sp, #64]
    stp x29, x30, [sp, #80]
    stp d8, d9, [sp, #96]
    stp d10, d11, [sp, #112]
    stp d12, d13, [sp, #128]
    stp d14, d15, [sp, #144]
    mov x2, sp
    str x2, [x0]
    mov sp, x1
    ldp x19, x20, [sp, #0]
    ldp x21, x22, [sp, #16]
    ldp x23, x24, [sp, #32]
    ldp x25, x26, [sp, #48]
    ldp x27, x28, [sp, #64]
    ldp x29, x30, [sp, #80]
    ldp d8, d9, [sp, #96]
    ldp d10, d11, [sp, #112]
    ldp d12, d13, [sp, #128]
    ldp d14, d15, [sp, #144]
    add sp, sp, #160
    ret

/* First code a new thread runs: x19 = entry, x20 = argument. */
.global thread_trampoline
thread_trampoline:
    msr daifclr, #2
    mov x0, x20
    blr x19
    bl rk_thread_exit
    brk #0
"#
);

unsafe fn table() -> &'static mut [Thread; MAX_THREADS] {
    &mut *core::ptr::addr_of_mut!(THREADS)
}

unsafe fn pick_next() -> Option<usize> {
    let t = table();
    (1..MAX_THREADS).map(|i| (CURRENT + i) % MAX_THREADS).find(|&i| t[i].state == State::Runnable)
}

unsafe fn switch_to(next: usize) {
    let t = table();
    let cur = CURRENT;
    if next == cur {
        return;
    }
    t[cur].tls = mpk_tls;
    mpk_tls = t[next].tls;
    t[next].switches += 1;
    CURRENT = next;
    SLICE_LEFT = SLICE;
    rk_switch_stacks(&mut t[cur].sp, t[next].sp);
}

/// Back to a single thread (the caller, which becomes thread 0's context).
pub unsafe fn reset(main_stack_top: u64) {
    let t = table();
    *t = [EMPTY; MAX_THREADS];
    t[0].state = State::Runnable;
    t[0].top = main_stack_top;
    CURRENT = 0;
    PREEMPT_VECTOR = u32::MAX;
    SLICE = 0;
}

/// Called from the interrupt dispatcher for every hardware interrupt.
pub unsafe fn on_interrupt(vector: u32) {
    let t = table();
    for th in t.iter_mut() {
        if th.state == State::Waiting {
            th.state = State::Runnable;
        }
    }
    if vector != PREEMPT_VECTOR {
        return;
    }
    t[CURRENT].ticks += 1;
    if SLICE == 0 {
        return;
    }
    SLICE_LEFT = SLICE_LEFT.saturating_sub(1);
    if SLICE_LEFT == 0 {
        match pick_next() {
            Some(next) => switch_to(next), // preempt: resumes here when rescheduled
            None => SLICE_LEFT = SLICE,
        }
    }
}

// ---- interface for the VM glue (mpy/mpthread.c) ----

#[no_mangle]
pub unsafe extern "C" fn rk_preempt(vector: u32, slice_ticks: u32) {
    let f = cpu::rk_irq_save();
    PREEMPT_VECTOR = vector;
    SLICE = slice_ticks;
    SLICE_LEFT = slice_ticks;
    cpu::rk_irq_restore(f);
}

/// Start a thread running `entry(arg)` on the given stack. Returns its id,
/// or -1 when the thread table is full.
#[no_mangle]
pub unsafe extern "C" fn rk_thread_create(entry: u64, arg: u64, stack: u64, size: u64) -> i32 {
    let f = cpu::rk_irq_save();
    let t = table();
    let slot = (1..MAX_THREADS).find(|&i| t[i].state == State::Free);
    if let Some(i) = slot {
        let top = (stack + size) & !15;
        #[cfg(target_arch = "x86_64")]
        let frame = {
            let frame = (top - 56) as *mut u64; // r15 r14 r13 r12 rbx rbp, return address
            frame.write(0);
            frame.add(1).write(0);
            frame.add(2).write(entry);
            frame.add(3).write(arg);
            frame.add(4).write(0);
            frame.add(5).write(0);
            frame.add(6).write(thread_trampoline as *const () as u64);
            frame
        };
        #[cfg(target_arch = "aarch64")]
        let frame = {
            let frame = (top - 160) as *mut u64; // x19..x30, d8..d15
            for k in 0..20 {
                frame.add(k).write(0);
            }
            frame.write(entry);
            frame.add(1).write(arg);
            frame.add(11).write(thread_trampoline as *const () as u64);
            frame
        };
        t[i] = Thread { sp: frame as u64, top, tls: 0, state: State::Runnable, ticks: 0, switches: 0 };
    }
    cpu::rk_irq_restore(f);
    slot.map_or(-1, |i| i as i32)
}

#[no_mangle]
pub unsafe extern "C" fn rk_thread_current() -> u32 {
    CURRENT as u32
}

/// Give the CPU to the next runnable thread, if there is one.
#[no_mangle]
pub unsafe extern "C" fn rk_thread_yield() {
    let f = cpu::rk_irq_save();
    if let Some(next) = pick_next() {
        switch_to(next);
    }
    cpu::rk_irq_restore(f);
}

/// Sleep until the next interrupt, letting other threads run meanwhile and
/// halting the CPU when nobody can. Call with interrupts disabled, passing
/// the flags from `rk_irq_save`; if they were already disabled before that,
/// this returns at once (the caller is polling).
#[no_mangle]
pub unsafe extern "C" fn rk_thread_wait(flags: u64) {
    if flags & 0x200 == 0 {
        return;
    }
    let cur = CURRENT;
    table()[cur].state = State::Waiting;
    loop {
        if let Some(next) = pick_next() {
            switch_to(next);
            break; // only runnable threads get switched back in
        }
        idle();
        if table()[cur].state == State::Runnable {
            break;
        }
    }
    table()[cur].state = State::Runnable;
    cpu::rk_sti();
}

/// End the calling thread. Never returns.
#[no_mangle]
pub unsafe extern "C" fn rk_thread_exit() -> ! {
    cpu::rk_cli();
    table()[CURRENT].state = State::Free;
    loop {
        if let Some(next) = pick_next() {
            switch_to(next);
        }
        idle();
    }
}

/// Let interrupts in and sleep until one comes; back with them masked.
/// (no `nomem`: interrupt handlers change thread states while halted)
#[inline(always)]
unsafe fn idle() {
    #[cfg(target_arch = "x86_64")]
    asm!("sti", "hlt", "cli", options(nostack));
    #[cfg(target_arch = "aarch64")]
    asm!("wfi", "msr daifclr, #2", "isb", "msr daifset, #2", options(nostack));
}

/// Saved stack range of a switched-out thread, for the garbage collector.
#[no_mangle]
pub unsafe extern "C" fn rk_thread_stack(i: u32, sp: *mut u64, top: *mut u64) -> bool {
    let i = i as usize;
    if i >= MAX_THREADS || i == CURRENT || table()[i].state == State::Free {
        return false;
    }
    *sp = table()[i].sp;
    *top = table()[i].top;
    true
}

/// The VM state pointer of thread `i` (0 if the slot is unused or the
/// thread has not entered the VM yet).
#[no_mangle]
pub unsafe extern "C" fn rk_thread_tls(i: u32) -> u64 {
    let i = i as usize;
    if i >= MAX_THREADS || table()[i].state == State::Free {
        return 0;
    }
    if i == CURRENT {
        mpk_tls
    } else {
        table()[i].tls
    }
}

/// out = [state, ticks, switches]; returns false for an unused slot.
#[no_mangle]
pub unsafe extern "C" fn rk_thread_info(i: u32, out: *mut u64) -> bool {
    let i = i as usize;
    if i >= MAX_THREADS || table()[i].state == State::Free {
        return false;
    }
    let th = table()[i];
    *out = if i == CURRENT { 3 } else { th.state as u64 };
    *out.add(1) = th.ticks;
    *out.add(2) = th.switches;
    true
}
