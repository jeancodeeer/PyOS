//! _kernel: the Python face of the Rust layer. Each function is the smallest
//! thing Python cannot do for itself (port I/O, interrupts, threads, memory,
//! the console); all policy built on them lives in Python (pyfs/lib/kernel).

use crate::port::{self, root_list, set_root, R_EXC, R_HISTORY, R_IDLE, R_IRQ, R_LINE, R_STDOUT};
use crate::py::{self, args, fun, int, new_uint, Fun, FunFixed, FunVar, Fn0, Fn1, Fn2, Obj, NONE};
use crate::{cpu, interrupts, sched};

fn u(o: Obj) -> u64 {
    int(o) as u64
}

extern "C" {
    fn mp_obj_new_tuple(n: usize, items: *const Obj) -> Obj;
    fn mp_obj_new_dict(n: usize) -> Obj;
    fn mp_obj_dict_store(d: Obj, k: Obj, v: Obj) -> Obj;
    fn mp_obj_new_list(n: usize, items: *const Obj) -> Obj;
    fn mp_obj_new_exception(ty: Obj) -> Obj;
    fn mp_obj_is_exception_type(o: Obj) -> bool;
    fn mp_obj_is_exception_instance(o: Obj) -> bool;
    fn mp_sched_schedule(f: Obj, arg: Obj) -> bool;
    fn gc_add(start: *mut u8, end: *mut u8);
}

fn tuple(items: &[Obj]) -> Obj {
    unsafe { mp_obj_new_tuple(items.len(), items.as_ptr()) }
}

// ---- port I/O ----

unsafe extern "C" fn inb(p: Obj) -> Obj {
    py::new_int(cpu::rk_inb(int(p) as u16) as i64)
}
unsafe extern "C" fn inw(p: Obj) -> Obj {
    py::new_int(cpu::rk_inw(int(p) as u16) as i64)
}
unsafe extern "C" fn inl(p: Obj) -> Obj {
    new_uint(cpu::rk_inl(int(p) as u16) as u64)
}
unsafe extern "C" fn outb(p: Obj, v: Obj) -> Obj {
    cpu::rk_outb(int(p) as u16, int(v) as u8);
    NONE
}
unsafe extern "C" fn outw(p: Obj, v: Obj) -> Obj {
    cpu::rk_outw(int(p) as u16, int(v) as u16);
    NONE
}
unsafe extern "C" fn outl(p: Obj, v: Obj) -> Obj {
    cpu::rk_outl(int(p) as u16, u(v) as u32);
    NONE
}
unsafe extern "C" fn insw(p: Obj, buf: Obj) -> Obj {
    let (b, n) = py::buffer(buf);
    cpu::rk_insw(int(p) as u16, b as *mut u16, n / 2);
    NONE
}
unsafe extern "C" fn outsw(p: Obj, buf: Obj) -> Obj {
    let (b, n) = py::buffer(buf);
    cpu::rk_outsw(int(p) as u16, b as *const u16, n / 2);
    NONE
}

// ---- the CPU ----

unsafe extern "C" fn irq_disable() -> Obj {
    py::boolean(cpu::rk_irq_save() & 0x200 != 0)
}
unsafe extern "C" fn irq_enable() -> Obj {
    cpu::rk_sti();
    NONE
}
unsafe extern "C" fn hlt() -> Obj {
    cpu::rk_hlt();
    NONE
}
unsafe extern "C" fn wait() -> Obj {
    port::gil_exit();
    cpu::rk_irq_save();
    sched::rk_thread_wait(0x200);
    port::gil_enter();
    NONE
}
unsafe extern "C" fn rdmsr(m: Obj) -> Obj {
    new_uint(cpu::rk_rdmsr(u(m) as u32))
}
unsafe extern "C" fn wrmsr(m: Obj, v: Obj) -> Obj {
    cpu::rk_wrmsr(u(m) as u32, u(v));
    NONE
}
unsafe extern "C" fn cpuid(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let mut r = [0u32; 4];
    cpu::rk_cpuid(u(a[0]) as u32, if n > 1 { u(a[1]) as u32 } else { 0 }, r.as_mut_ptr());
    tuple(&r.map(|v| new_uint(v as u64)))
}
unsafe extern "C" fn rdtsc() -> Obj {
    new_uint(cpu::rk_rdtsc())
}
unsafe extern "C" fn cr(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let reg = int(a[0]) as u32;
    if !matches!(reg, 0 | 2 | 3 | 4 | 8) {
        py::value_error(b"no such control register\0");
    }
    if n == 1 {
        return new_uint(cpu::rk_read_cr(reg));
    }
    cpu::rk_write_cr(reg, u(a[1]));
    NONE
}
unsafe extern "C" fn invlpg(a: Obj) -> Obj {
    cpu::rk_invlpg(u(a));
    NONE
}
unsafe extern "C" fn call(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    let mut v = [0u64; 6];
    for i in 1..n {
        v[i - 1] = u(a[i]);
    }
    new_uint(cpu::rk_call(u(a[0]), v[0], v[1], v[2], v[3], v[4], v[5]))
}

// ---- interrupts ----

unsafe extern "C" fn irq_handler(vec: Obj, f: Obj) -> Obj {
    let v = int(vec) as usize;
    if v > 255 {
        py::value_error(b"vector out of range\0");
    }
    let handlers = root_list(R_IRQ);
    let old = handlers[v];
    interrupts::rk_irq_arm(v as u32, false);
    handlers[v] = f;
    interrupts::rk_irq_ack(v as u32);
    interrupts::rk_irq_arm(v as u32, f != NONE);
    old
}
unsafe extern "C" fn irq_count(v: Obj) -> Obj {
    new_uint(interrupts::rk_irq_count(int(v) as u32))
}
unsafe extern "C" fn irq_dropped() -> Obj {
    new_uint(interrupts::rk_irq_dropped())
}
unsafe extern "C" fn irq_fifo(n: usize, a: *const Obj) -> Obj {
    let a = args(n, a);
    if !interrupts::rk_irq_fifo(int(a[0]) as u32, int(a[1]) as u16, int(a[2]) as u8, int(a[3]) as u8, int(a[4]) as u16) {
        py::os_error(b"no free irq fifo\0");
    }
    NONE
}
unsafe extern "C" fn irq_read(v: Obj) -> Obj {
    let mut buf = [0u8; 256];
    let n = interrupts::rk_irq_fifo_read(int(v) as u32, buf.as_mut_ptr(), buf.len());
    py::new_bytes(&buf[..n])
}
unsafe extern "C" fn irq_lost() -> Obj {
    new_uint(interrupts::rk_irq_fifo_lost())
}

/// Runs on the VM scheduler, shortly after interrupt `vec`.
unsafe extern "C" fn dispatch(vec: Obj) -> Obj {
    let v = (int(vec) & 0xFF) as usize;
    interrupts::rk_irq_ack(v as u32);
    let f = root_list(R_IRQ)[v];
    if f != NONE && f != 0 {
        port::call1(f, vec);
    }
    NONE
}
static DISPATCH: FunFixed<Fn1> = Fun::f1(dispatch);

/// Called by the interrupt dispatcher, in interrupt context.
#[no_mangle]
pub extern "C" fn mpk_schedule_irq(vector: u32) -> bool {
    unsafe { mp_sched_schedule(fun(&DISPATCH), py::new_int(vector as i64)) }
}

// ---- threads ----

unsafe extern "C" fn preempt(v: Obj, ticks: Obj) -> Obj {
    sched::rk_preempt(int(v) as u32, int(ticks) as u32);
    NONE
}
/// [(id, state, ticks, switches)]; state 1 ready, 2 asleep, 3 running.
unsafe extern "C" fn threads() -> Obj {
    let list = mp_obj_new_list(0, core::ptr::null());
    for i in 0..sched::MAX_THREADS as u32 {
        let mut v = [0u64; 3];
        if sched::rk_thread_info(i, v.as_mut_ptr()) {
            let t = tuple(&[py::new_int(i as i64), py::new_int(v[0] as i64), new_uint(v[1]), new_uint(v[2])]);
            py::list_append(list, t);
        }
    }
    list
}
unsafe extern "C" fn thread_raise(id: Obj, exc: Obj) -> Obj {
    let e = if mp_obj_is_exception_type(exc) {
        mp_obj_new_exception(exc)
    } else if mp_obj_is_exception_instance(exc) {
        exc
    } else {
        py::type_error(b"exceptions must derive from BaseException\0");
    };
    if !port::async_raise(int(id) as usize, e) {
        py::value_error(b"no such thread\0");
    }
    NONE
}
/// thread_mask(True/False): while masked, the calling thread cannot be hit
/// by an exception from outside (kill, thread.interrupt, Ctrl-C); it is held
/// and raised when the mask is lifted. Interrupt handlers and tasks are held
/// back too. Used around work that must not be abandoned half-way (a
/// filesystem update). Calls nest.
unsafe extern "C" fn thread_mask(on: Obj) -> Obj {
    port::thread_mask(py::truthy(on));
    NONE
}

// ---- the console ----

unsafe extern "C" fn hook(slot: usize, f: Obj) -> Obj {
    set_root(slot, f)
}
unsafe extern "C" fn stdout_hook(f: Obj) -> Obj {
    hook(R_STDOUT, f)
}
unsafe extern "C" fn idle_hook(f: Obj) -> Obj {
    hook(R_IDLE, f)
}
unsafe extern "C" fn exc_hook(f: Obj) -> Obj {
    hook(R_EXC, f)
}
unsafe extern "C" fn line_editor(f: Obj) -> Obj {
    hook(R_LINE, f)
}
unsafe extern "C" fn history() -> Obj {
    let h = py::items(port::root(R_HISTORY));
    mp_obj_new_list(h.len(), h.as_ptr())
}
unsafe extern "C" fn history_add(line: Obj) -> Obj {
    let s = port::str_bytes(line);
    let mut z = [0u8; 512];
    let k = s.len().min(511);
    z[..k].copy_from_slice(&s[..k]);
    port::readline_push_history(z.as_ptr());
    NONE
}
unsafe extern "C" fn stdin_pending() -> Obj {
    py::boolean(!crate::rk_stdin_empty())
}
unsafe extern "C" fn stdin_push(o: Obj) -> Obj {
    if o & 1 == 1 {
        port::mpk_feed((int(o) & 0xFF) as i32);
    } else {
        for &b in py::bytes(o) {
            port::mpk_feed(b as i32);
        }
    }
    NONE
}
unsafe extern "C" fn serial_write(o: Obj) -> Obj {
    crate::serial::write(py::bytes(o));
    NONE
}
unsafe extern "C" fn klog() -> Obj {
    let mut buf = [0u8; 8192];
    let n = crate::serial::rk_klog(buf.as_mut_ptr(), buf.len());
    py::new_bytes(&buf[..n])
}

// ---- memory ----

const INFO_NAMES: [&str; 29] = [
    "kernel_start", "kernel_end", "heap_start", "heap_end", "multiboot", "initrd_start", "initrd_end",
    "stack_base", "stack_top", "idt", "boots", "pool_start", "pool_end",
    "arch", "fb_addr", "fb_width", "fb_height", "fb_pitch", "fb_format", "rsdp", "epoch", "ecam", "pio",
    "psci", "timer_hz", "mmap", "mmap_size", "mmap_desc", "timer_irq",
];

unsafe extern "C" fn info() -> Obj {
    let d = mp_obj_new_dict(INFO_NAMES.len());
    for (i, name) in INFO_NAMES.iter().enumerate() {
        mp_obj_dict_store(d, py::qstr_obj(name), new_uint(crate::rk_info(i as u32)));
    }
    d
}

// The heap's reserve (info pool_start..pool_end): MicroPython takes more heap
// from it by itself when it runs short (MICROPY_GC_SPLIT_HEAP_AUTO).
const POOL_SLOTS: usize = 64;
static mut FREE: [(usize, usize); POOL_SLOTS] = [(0, 0); POOL_SLOTS];   // (address, length)
static mut USED: [(usize, usize); POOL_SLOTS] = [(0, 0); POOL_SLOTS];
static mut N_FREE: isize = -1;
static mut N_USED: usize = 0;

unsafe fn pool_init() {
    if N_FREE >= 0 {
        return;
    }
    N_FREE = 0;
    let (s, e) = (crate::rk_info(11) as usize, crate::rk_info(12) as usize);
    if e > s {
        FREE[0] = (s, e - s);
        N_FREE = 1;
    }
}

#[no_mangle]
pub unsafe extern "C" fn mpk_heap_alloc(size: usize) -> *mut u8 {
    pool_init();
    let size = (size + 4095) & !4095;
    if N_USED >= POOL_SLOTS {
        return core::ptr::null_mut();
    }
    for i in 0..N_FREE as usize {
        if FREE[i].1 >= size {
            let p = FREE[i].0;
            FREE[i].0 += size;
            FREE[i].1 -= size;
            USED[N_USED] = (p, size);
            N_USED += 1;
            return p as *mut u8;
        }
    }
    core::ptr::null_mut()
}

#[no_mangle]
pub unsafe extern "C" fn mpk_heap_free(ptr: *mut u8) {
    let p = ptr as usize;
    for i in 0..N_USED {
        if USED[i].0 == p {
            let len = USED[i].1;
            N_USED -= 1;
            USED[i] = USED[N_USED];
            for k in 0..N_FREE as usize {                 // join a free neighbour
                if FREE[k].0 + FREE[k].1 == p {
                    FREE[k].1 += len;
                    return;
                }
                if p + len == FREE[k].0 {
                    FREE[k] = (p, FREE[k].1 + len);
                    return;
                }
            }
            if (N_FREE as usize) < POOL_SLOTS {
                FREE[N_FREE as usize] = (p, len);
                N_FREE += 1;
            }
            return;
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn gc_get_max_new_split() -> usize {
    pool_init();
    (0..N_FREE as usize).map(|i| FREE[i].1).max().unwrap_or(0)
}

unsafe extern "C" fn heap_pool() -> Obj {
    pool_init();
    let free: usize = (0..N_FREE as usize).map(|i| FREE[i].1).sum();
    tuple(&[new_uint(crate::rk_info(12) - crate::rk_info(11)), new_uint(free as u64)])
}
unsafe extern "C" fn heap_add(addr: Obj, size: Obj) -> Obj {
    let a = u(addr) as usize;
    gc_add(a as *mut u8, (a + u(size) as usize) as *mut u8);
    NONE
}

// ---- the module ----

static INB: FunFixed<Fn1> = Fun::f1(inb);
static INW: FunFixed<Fn1> = Fun::f1(inw);
static INL: FunFixed<Fn1> = Fun::f1(inl);
static OUTB: FunFixed<Fn2> = Fun::f2(outb);
static OUTW: FunFixed<Fn2> = Fun::f2(outw);
static OUTL: FunFixed<Fn2> = Fun::f2(outl);
static INSW: FunFixed<Fn2> = Fun::f2(insw);
static OUTSW: FunFixed<Fn2> = Fun::f2(outsw);
static IRQ_DISABLE: FunFixed<Fn0> = Fun::f0(irq_disable);
static IRQ_ENABLE: FunFixed<Fn0> = Fun::f0(irq_enable);
static HLT: FunFixed<Fn0> = Fun::f0(hlt);
static WAIT: FunFixed<Fn0> = Fun::f0(wait);
static RDMSR: FunFixed<Fn1> = Fun::f1(rdmsr);
static WRMSR: FunFixed<Fn2> = Fun::f2(wrmsr);
static CPUID: FunVar = Fun::var(1, 2, cpuid);
static RDTSC: FunFixed<Fn0> = Fun::f0(rdtsc);
static CR: FunVar = Fun::var(1, 2, cr);
static INVLPG: FunFixed<Fn1> = Fun::f1(invlpg);
static CALL: FunVar = Fun::var(1, 7, call);
static IRQ_HANDLER: FunFixed<Fn2> = Fun::f2(irq_handler);
static IRQ_COUNT: FunFixed<Fn1> = Fun::f1(irq_count);
static IRQ_DROPPED: FunFixed<Fn0> = Fun::f0(irq_dropped);
static IRQ_FIFO: FunVar = Fun::var(5, 5, irq_fifo);
static IRQ_READ: FunFixed<Fn1> = Fun::f1(irq_read);
static IRQ_LOST: FunFixed<Fn0> = Fun::f0(irq_lost);
static PREEMPT: FunFixed<Fn2> = Fun::f2(preempt);
static THREADS: FunFixed<Fn0> = Fun::f0(threads);
static THREAD_RAISE: FunFixed<Fn2> = Fun::f2(thread_raise);
static THREAD_MASK: FunFixed<Fn1> = Fun::f1(thread_mask);
static STDOUT_HOOK: FunFixed<Fn1> = Fun::f1(stdout_hook);
static IDLE_HOOK: FunFixed<Fn1> = Fun::f1(idle_hook);
static EXC_HOOK: FunFixed<Fn1> = Fun::f1(exc_hook);
static LINE_EDITOR: FunFixed<Fn1> = Fun::f1(line_editor);
static HISTORY: FunFixed<Fn0> = Fun::f0(history);
static HISTORY_ADD: FunFixed<Fn1> = Fun::f1(history_add);
static STDIN_PENDING: FunFixed<Fn0> = Fun::f0(stdin_pending);
static STDIN_PUSH: FunFixed<Fn1> = Fun::f1(stdin_push);
static SERIAL_WRITE: FunFixed<Fn1> = Fun::f1(serial_write);
static KLOG: FunFixed<Fn0> = Fun::f0(klog);
static INFO: FunFixed<Fn0> = Fun::f0(info);
static HEAP_POOL: FunFixed<Fn0> = Fun::f0(heap_pool);
static HEAP_ADD: FunFixed<Fn2> = Fun::f2(heap_add);

/// `import _kernel` (once per Python session, from main.rs).
pub fn register() {
    let m = py::define("_kernel", &[
        ("inb", fun(&INB)), ("inw", fun(&INW)), ("inl", fun(&INL)), ("outb", fun(&OUTB)), ("outw", fun(&OUTW)),
        ("outl", fun(&OUTL)), ("insw", fun(&INSW)), ("outsw", fun(&OUTSW)),
        ("irq_disable", fun(&IRQ_DISABLE)), ("irq_enable", fun(&IRQ_ENABLE)), ("hlt", fun(&HLT)), ("wait", fun(&WAIT)),
        ("rdmsr", fun(&RDMSR)), ("wrmsr", fun(&WRMSR)), ("cpuid", fun(&CPUID)), ("rdtsc", fun(&RDTSC)),
        ("cr", fun(&CR)), ("invlpg", fun(&INVLPG)), ("call", fun(&CALL)),
        ("irq_handler", fun(&IRQ_HANDLER)), ("irq_count", fun(&IRQ_COUNT)), ("irq_dropped", fun(&IRQ_DROPPED)),
        ("irq_fifo", fun(&IRQ_FIFO)), ("irq_read", fun(&IRQ_READ)), ("irq_lost", fun(&IRQ_LOST)),
        ("preempt", fun(&PREEMPT)), ("threads", fun(&THREADS)), ("thread_raise", fun(&THREAD_RAISE)),
        ("thread_mask", fun(&THREAD_MASK)),
        ("stdout_hook", fun(&STDOUT_HOOK)), ("idle_hook", fun(&IDLE_HOOK)), ("exc_hook", fun(&EXC_HOOK)),
        ("line_editor", fun(&LINE_EDITOR)), ("history", fun(&HISTORY)), ("history_add", fun(&HISTORY_ADD)),
        ("stdin_pending", fun(&STDIN_PENDING)), ("stdin_push", fun(&STDIN_PUSH)), ("serial_write", fun(&SERIAL_WRITE)),
        ("klog", fun(&KLOG)), ("info", fun(&INFO)), ("heap_pool", fun(&HEAP_POOL)), ("heap_add", fun(&HEAP_ADD)),
        ("repl", fun(&port::REPL)), ("repl_exec", fun(&port::REPL_EXEC)), ("repl_continue", fun(&port::REPL_CONTINUE)),
    ]);
    port::make_roots(m);
}
