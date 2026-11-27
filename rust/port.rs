//! The MicroPython port: what the VM needs from the system (console input
//! and output, threads and locks, garbage collection roots, the REPL), the
//! hooks Python fills in (console driver, line editor, exception printer),
//! and catching Python exceptions from Rust.
//!
//! MicroPython is C; it calls the `#[no_mangle]` functions below by name.

use crate::py::{self, Obj, NONE};
use core::ffi::c_void;
use core::sync::atomic::{AtomicI32, Ordering::SeqCst};

// ---- the parts of MicroPython's state this port reads and writes ----

/// mp_state_thread_t (py/mpstate.h) with this port's configuration:
/// MICROPY_STACK_CHECK on, no pystack, no settrace. Checked at start-up
/// (`check_layout`).
#[repr(C)]
pub struct ThreadState {
    pub stack_top: *mut u8,
    pub stack_limit: usize,
    pub gc_lock_depth: u16,
    pub dict_locals: Obj,
    pub dict_globals: Obj,
    pub nlr_top: usize,
    pub nlr_jump_callback_top: usize,
    pub pending_exception: Obj,
    pub stop_iteration_arg: Obj,
}

#[repr(C)]
struct ParseTree {
    root: usize,
    chunk: usize,
}

extern "C" {
    static mut mp_state_ctx: ThreadState;      // the main thread's state comes first
    static mp_plat_print: u8;
    static mp_type_KeyboardInterrupt: u8;
    static mut mp_interrupt_char: i32;
    static mut pyexec_mode_kind: i32;

    fn nlr_pop();
    fn nlr_jump(val: *mut c_void) -> !;
    fn __real_mp_obj_print_exception(print: *const u8, exc: Obj);
    fn mp_call_function_0(f: Obj) -> Obj;
    fn mp_call_function_1(f: Obj, a: Obj) -> Obj;
    fn mp_call_function_2(f: Obj, a: Obj, b: Obj) -> Obj;
    fn mp_obj_get_type(o: Obj) -> Obj;
    fn mp_obj_is_subclass_fast(a: Obj, b: Obj) -> bool;
    fn mp_obj_new_str(data: *const u8, len: usize) -> Obj;
    fn mp_obj_str_get_data(o: Obj, len: *mut usize) -> *const u8;
    fn mp_obj_new_list(n: usize, items: *const Obj) -> Obj;
    fn mp_obj_list_append(list: Obj, item: Obj) -> Obj;
    fn mp_obj_exception_clear_traceback(exc: Obj);
    fn mp_sched_schedule(f: Obj, arg: Obj) -> bool;
    fn mp_sched_keyboard_interrupt();
    fn mp_handle_pending(raise: bool);
    fn mp_lexer_new_from_str_len(name: usize, s: *const u8, len: usize, free_len: usize) -> *mut c_void;
    fn mp_parse(lex: *mut c_void, kind: i32) -> ParseTree;
    fn mp_compile(tree: *mut ParseTree, source: usize, is_repl: bool) -> Obj;
    fn mp_import_name(name: usize, fromlist: Obj, level: Obj) -> Obj;
    fn mp_hal_set_interrupt_char(c: i32);
    fn mp_repl_continue_with_input(s: *const u8) -> bool;
    fn pyexec_friendly_repl() -> i32;
    fn pyexec_raw_repl() -> i32;
    fn gc_collect_start();
    fn gc_helper_collect_regs_and_stack();
    fn gc_collect_root(ptrs: *mut *mut c_void, len: usize);
    fn gc_collect_end();
    fn gc_is_locked() -> bool;
    fn m_malloc(n: usize) -> *mut u8;
    fn m_free(p: *mut u8);
    fn vstr_add_strn(v: *mut c_void, s: *const u8, len: usize);
    fn mp_raise_msg_varg(ty: *const u8, fmt: *const u8, ...) -> !;
    fn mp_printf(print: *const u8, fmt: *const u8, ...) -> i32;
    static mp_type_RuntimeError: u8;
    static mp_type_OSError: u8;
}

// ---- catching exceptions: nlr_push from assembly (it returns twice) ----

extern "C" {
    /// Run f(ctx) inside an nlr frame. Returns 0, or the exception it raised.
    fn rk_try(f: unsafe extern "C" fn(*mut c_void), ctx: *mut c_void) -> Obj;
}

#[cfg(target_arch = "x86_64")]
core::arch::global_asm!(
    r#"
.global rk_try
rk_try:
    push rbp
    mov rbp, rsp
    sub rsp, 512
    mov [rbp - 8], rdi
    mov [rbp - 16], rsi
    lea rdi, [rbp - 512]
    call nlr_push
    test eax, eax
    jnz 1f
    mov rdi, [rbp - 16]
    call qword ptr [rbp - 8]
    call nlr_pop
    xor eax, eax
    leave
    ret
1:  mov rax, [rbp - 504]
    leave
    ret
"#
);

#[cfg(target_arch = "aarch64")]
core::arch::global_asm!(
    r#"
.global rk_try
rk_try:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    sub sp, sp, #512
    str x0, [sp, #480]
    str x1, [sp, #488]
    mov x0, sp
    bl nlr_push
    cbnz w0, 1f
    ldr x0, [sp, #488]
    ldr x2, [sp, #480]
    blr x2
    bl nlr_pop
    mov x0, #0
    b 2f
1:  ldr x0, [sp, #8]
2:  add sp, sp, #512
    ldp x29, x30, [sp], #16
    ret
"#
);

/// Run `f`; Err(exception) if it raised. (No values with destructors may
/// live in `f`: a raise skips straight back here.)
pub fn protect<F: FnMut()>(mut f: F) -> Result<(), Obj> {
    unsafe extern "C" fn call<F: FnMut()>(ctx: *mut c_void) {
        (*(ctx as *mut F))()
    }
    match unsafe { rk_try(call::<F>, &mut f as *mut F as *mut c_void) } {
        0 => Ok(()),
        exc => Err(exc),
    }
}

pub fn raise(exc: Obj) -> ! {
    unsafe { nlr_jump(exc as *mut c_void) }
}

pub fn call0(f: Obj) -> Obj {
    unsafe { mp_call_function_0(f) }
}
pub fn call1(f: Obj, a: Obj) -> Obj {
    unsafe { mp_call_function_1(f, a) }
}
pub fn call2(f: Obj, a: Obj, b: Obj) -> Obj {
    unsafe { mp_call_function_2(f, a, b) }
}

pub fn print_exception(exc: Obj) {
    unsafe { __wrap_mp_obj_print_exception(core::ptr::addr_of!(mp_plat_print), exc) }
}

fn is_keyboard_interrupt(exc: Obj) -> bool {
    unsafe { mp_obj_is_subclass_fast(mp_obj_get_type(exc), core::ptr::addr_of!(mp_type_KeyboardInterrupt) as Obj) }
}

pub fn new_str(s: &[u8]) -> Obj {
    unsafe { mp_obj_new_str(s.as_ptr(), s.len()) }
}
/// The bytes of a str object.
pub fn str_bytes<'a>(o: Obj) -> &'a [u8] {
    let mut n = 0;
    unsafe {
        let p = mp_obj_str_get_data(o, &mut n);
        core::slice::from_raw_parts(p, n)
    }
}

fn say(s: &str) {
    unsafe { mp_printf(core::ptr::addr_of!(mp_plat_print), b"%.*s\0".as_ptr(), s.len() as i32, s.as_ptr()) };
}

// ---- objects Python hands to the kernel: kept in a list the GC can see ----

pub const R_STDOUT: usize = 0;
pub const R_IDLE: usize = 1;
pub const R_EXC: usize = 2;
pub const R_LINE: usize = 3;
pub const R_REPL: usize = 4;
pub const R_HISTORY: usize = 5;
pub const R_IRQ: usize = 6;          // a list of 256 handlers
pub const R_STACKS: usize = 7;       // a list of 32 thread stacks
pub const R_DEFERRED: usize = 8;     // a list of 32 held-back exceptions
const R_COUNT: usize = 9;

static mut ROOTS: Obj = 0;

fn new_list(n: usize) -> Obj {
    let l = unsafe { mp_obj_new_list(n, core::ptr::null()) };
    for slot in py::items_mut(l) {
        *slot = NONE;
    }
    l
}

/// Make the roots list (once per Python session) and hang it on `module`.
pub fn make_roots(module: Obj) {
    let roots = new_list(R_COUNT);
    unsafe { ROOTS = roots };
    let r = py::items_mut(roots);
    r[R_HISTORY] = new_list(0);
    r[R_IRQ] = new_list(256);
    r[R_STACKS] = new_list(32);
    r[R_DEFERRED] = new_list(32);
    py::set(module, "__roots__", roots);
}

pub fn root(i: usize) -> Obj {
    unsafe { if ROOTS == 0 { NONE } else { py::items(ROOTS)[i] } }
}
pub fn set_root(i: usize, v: Obj) -> Obj {
    let r = py::items_mut(unsafe { ROOTS });
    core::mem::replace(&mut r[i], v)
}
pub fn root_list<'a>(i: usize) -> &'a mut [Obj] {
    py::items_mut(root(i))
}
fn is_set(o: Obj) -> bool {
    o != NONE && o != 0
}

// ---- the thread state, the GIL and start-up checks ----

#[no_mangle]
pub static mut mpk_tls: u64 = 0;       // the current thread's mp_state_thread_t (rust/sched.rs switches it)

pub fn tls() -> *mut ThreadState {
    unsafe { mpk_tls as *mut ThreadState }
}

static mut GIL: *const Mutex = core::ptr::null();
static mut LAST_MUTEX: *const Mutex = core::ptr::null();
static mut KBD_EXC: Obj = 0;

pub fn gil_exit() {
    unsafe {
        if !GIL.is_null() {
            mp_thread_mutex_unlock(GIL as *mut Mutex);
        }
    }
}
pub fn gil_enter() {
    unsafe {
        if !GIL.is_null() {
            mp_thread_mutex_lock(GIL as *mut Mutex, 1);
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn mpk_cstack_init(top: *const u8, size: usize) {
    mpk_tls = core::ptr::addr_of_mut!(mp_state_ctx) as u64;     // we are the main thread
    (*tls()).stack_top = top as *mut u8;
    (*tls()).stack_limit = size;                                // MICROPY_STACK_CHECK_MARGIN is 0
}

/// Right after mp_init: find the GIL (the last mutex mp_init made) and the
/// KeyboardInterrupt object, and check our picture of the thread state.
pub fn after_mp_init() {
    unsafe {
        GIL = LAST_MUTEX;
        if GIL.is_null() || (*GIL).locked.load(SeqCst) != 1 {
            crate::klog!("port: the GIL was not found where expected");
        }
        let ts = tls();
        let f = crate::cpu::rk_irq_save();
        mp_sched_keyboard_interrupt();                // sets the main thread's pending exception
        KBD_EXC = (*ts).pending_exception;
        (*ts).pending_exception = 0;
        crate::cpu::rk_irq_restore(f);
        mp_handle_pending(false);                     // and the scheduler back to idle
        if KBD_EXC == 0 {
            crate::klog!("port: mp_state_thread_t does not match rust/port.rs: Ctrl-C will not work");
        }
    }
}

/// Once per Python session, before init.py runs.
pub fn init() {
    for i in 0..32 {
        unsafe { ASYNC_MASK[i] = 0 };
    }
}

// ---- threads (MicroPython's port interface) ----

#[repr(C)]
pub struct Mutex {
    locked: AtomicI32,
    waiters: AtomicI32,
}

#[no_mangle]
pub unsafe extern "C" fn mp_thread_get_state() -> *mut ThreadState {
    tls()
}
#[no_mangle]
pub unsafe extern "C" fn mp_thread_set_state(s: *mut ThreadState) {
    mpk_tls = s as u64;
}
#[no_mangle]
pub extern "C" fn mp_thread_get_id() -> usize {
    unsafe { crate::sched::rk_thread_current() as usize }
}
#[no_mangle]
pub extern "C" fn mp_thread_start() {}
#[no_mangle]
pub extern "C" fn mp_thread_finish() {}

#[repr(C)]
struct Launch {
    entry: unsafe extern "C" fn(*mut c_void) -> *mut c_void,
    arg: *mut c_void,
}

unsafe extern "C" fn thread_main(p: u64) {
    let l = &*(p as *const Launch);
    (l.entry)(l.arg);
    let me = crate::sched::rk_thread_current() as usize;
    async_exit(me);
    crate::cpu::rk_cli();
    root_list(R_STACKS)[me & 31] = NONE;
    crate::sched::rk_thread_exit();
}

const STACK_DEFAULT: usize = 128 * 1024;
const STACK_MIN: usize = 32 * 1024;

#[no_mangle]
pub unsafe extern "C" fn mp_thread_create(entry: unsafe extern "C" fn(*mut c_void) -> *mut c_void, arg: *mut c_void,
                                          stack_size: *mut usize) -> usize {
    let size = match *stack_size {
        0 => STACK_DEFAULT,
        s => s.max(STACK_MIN),
    };
    *stack_size = size;
    let stack = m_malloc(size);
    let launch = stack as *mut Launch;                // parked at the unused low end
    (*launch).entry = entry;
    (*launch).arg = arg;
    let id = crate::sched::rk_thread_create(thread_main as usize as u64, launch as u64, stack as u64 + 64, size as u64 - 64);
    if id < 0 {
        m_free(stack);
        py::os_error(b"too many threads\0");
    }
    root_list(R_STACKS)[id as usize] = stack as Obj;      // keeps the stack alive
    async_reset(id as usize);
    *stack_size -= 8 * 1024;                              // headroom for the stack-overflow check
    id as usize
}

#[no_mangle]
pub unsafe extern "C" fn mp_thread_mutex_init(m: *mut Mutex) {
    (*m).locked.store(0, SeqCst);
    (*m).waiters.store(0, SeqCst);
    LAST_MUTEX = m;
}

#[no_mangle]
pub unsafe extern "C" fn mp_thread_mutex_lock(m: *mut Mutex, wait: i32) -> i32 {
    let m = &*m;
    if m.locked.swap(1, SeqCst) == 0 {
        return 1;
    }
    if wait == 0 {
        return 0;
    }
    m.waiters.fetch_add(1, SeqCst);
    while m.locked.swap(1, SeqCst) != 0 {
        crate::sched::rk_thread_yield();
    }
    m.waiters.fetch_sub(1, SeqCst);
    1
}

#[no_mangle]
pub unsafe extern "C" fn mp_thread_mutex_unlock(m: *mut Mutex) {
    let m = &*m;
    m.locked.store(0, SeqCst);
    if m.waiters.load(SeqCst) != 0 {
        crate::sched::rk_thread_yield();              // hand over instead of re-grabbing
    }
}

// ---- garbage collection ----

#[no_mangle]
pub unsafe extern "C" fn gc_collect() {
    gc_collect_start();
    gc_helper_collect_regs_and_stack();
    for i in 0..crate::sched::MAX_THREADS as u32 {      // the other threads' stacks
        let (mut sp, mut top) = (0u64, 0u64);
        if crate::sched::rk_thread_stack(i, &mut sp, &mut top) {
            gc_collect_root(sp as *mut *mut c_void, ((top - sp) / 8) as usize);
        }
    }
    gc_collect_end();
}

#[no_mangle]
pub extern "C" fn nlr_jump_fail(val: *mut c_void) -> ! {
    crate::rk_fatal(val as u64)
}

// ---- exceptions from outside a thread (kill, thread.interrupt, Ctrl-C) ----

static mut ASYNC_MASK: [u8; 32] = [0; 32];

pub fn async_reset(id: usize) {
    unsafe { ASYNC_MASK[id & 31] = 0 };
    root_list(R_DEFERRED)[id & 31] = NONE;
}

/// A thread is ending: drop any mask it still holds.
pub fn async_exit(id: usize) {
    unsafe {
        if ASYNC_MASK[id & 31] != 0 {
            ASYNC_MASK[id & 31] = 0;
            crate::py::sched_unlock();
        }
    }
    root_list(R_DEFERRED)[id & 31] = NONE;
}

/// Make thread `id` raise `exc` at its next bytecode boundary, or when it
/// lifts its mask.
pub fn async_raise(id: usize, exc: Obj) -> bool {
    if id >= 32 {
        return false;
    }
    let ts = unsafe { crate::sched::rk_thread_tls(id as u32) } as *mut ThreadState;
    if ts.is_null() {
        return false;
    }
    unsafe {
        if ASYNC_MASK[id] != 0 {
            root_list(R_DEFERRED)[id] = exc;
        } else {
            (*ts).pending_exception = exc;
        }
    }
    true
}

/// thread_mask(on): see kmod.rs.
pub fn thread_mask(on: bool) {
    let id = (unsafe { crate::sched::rk_thread_current() } & 31) as usize;
    unsafe {
        if on {
            if ASYNC_MASK[id] == 0 {
                crate::py::sched_lock();
            }
            ASYNC_MASK[id] += 1;
        } else if ASYNC_MASK[id] != 0 {
            ASYNC_MASK[id] -= 1;
            if ASYNC_MASK[id] == 0 {
                crate::py::sched_unlock();
                let d = &mut root_list(R_DEFERRED)[id];
                if is_set(*d) {
                    let exc = core::mem::replace(d, NONE);
                    raise(exc);                        // raised right here, as the protected work ends
                }
            }
        }
    }
}

// ---- console input ----

fn raise_kbd_interrupt() {
    unsafe {
        if KBD_EXC != 0 {
            mp_obj_exception_clear_traceback(KBD_EXC);
            async_raise(0, KBD_EXC);
        }
    }
}

unsafe extern "C" fn deliver_kbd_interrupt(_unused: Obj) -> Obj {
    raise_kbd_interrupt();
    NONE
}
static DELIVER_KBD: py::FunFixed<py::Fn1> = py::Fun::f1(deliver_kbd_interrupt);

/// One byte of console input, from whichever driver produced it.
#[no_mangle]
pub extern "C" fn mpk_feed(c: i32) {
    if c == unsafe { mp_interrupt_char } {
        // from an interrupt handler: raise Ctrl-C from a scheduled callback,
        // so it lands in the interrupted program, not in the driver
        if !unsafe { mp_sched_schedule(py::fun(&DELIVER_KBD), NONE) } {
            raise_kbd_interrupt();
        }
    } else {
        crate::rk_stdin_push(c as u8);
    }
}

/// The Python idle hook, once, when the console runs out of input (the safe
/// moment for housekeeping such as saving the history). A hook that raises
/// is unregistered.
fn run_idle_hook() {
    let hook = root(R_IDLE);
    if !is_set(hook) {
        return;
    }
    if let Err(exc) = protect(|| {
        call0(hook);
    }) {
        set_root(R_IDLE, NONE);
        say("\r\n[idle hook failed; removed]\r\n");
        print_exception(exc);
    }
}

/// Wait for a console byte, letting interrupt handlers and other threads run.
#[no_mangle]
pub unsafe extern "C" fn mp_hal_stdin_rx_chr() -> i32 {
    let mut idle_done = false;
    loop {
        let c = crate::rk_stdin_pop();
        if c >= 0 {
            return c;
        }
        mp_handle_pending(true);
        if !idle_done && mp_thread_get_id() == 0 {
            idle_done = true;
            run_idle_hook();
            continue;
        }
        let c = crate::serial::rk_serial_rx();          // serial input works even with no driver loaded
        if c >= 0 {
            mpk_feed(c);
            continue;
        }
        let flags = crate::cpu::rk_irq_save();
        if crate::rk_stdin_empty() {
            gil_exit();                                   // others may use the VM while we sleep
            crate::sched::rk_thread_wait(flags);
            crate::cpu::rk_irq_restore(flags);
            gil_enter();
        } else {
            crate::cpu::rk_irq_restore(flags);
        }
    }
}

#[no_mangle]
pub extern "C" fn mp_hal_stdio_poll(flags: usize) -> usize {
    let mut ret = flags & 4;                              // MP_STREAM_POLL_WR
    if flags & 1 != 0 && !crate::rk_stdin_empty() {
        ret |= 1;                                         // MP_STREAM_POLL_RD
    }
    ret
}

// ---- console output: the Python console driver, else the serial port ----

static mut IN_HOOK: bool = false;
static mut HOOK_OWNER: usize = usize::MAX;

#[no_mangle]
pub unsafe extern "C" fn mp_hal_stdout_tx_strn(s: *const u8, len: usize) -> usize {
    let me = mp_thread_get_id();
    while IN_HOOK && HOOK_OWNER != me {                   // one thread at a time drives the console
        gil_exit();
        crate::sched::rk_thread_yield();
        gil_enter();
    }
    let hook = root(R_STDOUT);
    let data = core::slice::from_raw_parts(s, len);
    if !is_set(hook) || IN_HOOK || gc_is_locked() {
        crate::serial::write(data);
        return len;
    }
    IN_HOOK = true;
    HOOK_OWNER = me;
    let r = protect(|| {
        call1(hook, py::new_bytes(data));
    });
    IN_HOOK = false;
    if let Err(exc) = r {
        if is_keyboard_interrupt(exc) {
            raise(exc);
        }
        set_root(R_STDOUT, NONE);                         // a broken console never silences the system
        crate::serial::write(data);
        crate::serial::write(b"\r\n[console driver failed; output now goes to serial]\r\n");
        print_exception(exc);
    }
    len
}

// ---- exceptions are printed by Python (kernel/errors.py) when it can ----

static mut PRINTING: bool = false;

#[no_mangle]
pub unsafe extern "C" fn __wrap_mp_obj_print_exception(print: *const u8, exc: Obj) {
    let hook = root(R_EXC);
    if print != core::ptr::addr_of!(mp_plat_print) || PRINTING || !is_set(hook) || gc_is_locked() {
        __real_mp_obj_print_exception(print, exc);
        return;
    }
    PRINTING = true;
    if protect(|| {
        call1(hook, exc);
    })
    .is_err()
    {
        set_root(R_EXC, NONE);
        __real_mp_obj_print_exception(print, exc);
    }
    PRINTING = false;
}

// ---- reading a line: the Python line editor, else a plain one ----

const HISTORY_MAX: usize = 100;

#[no_mangle]
pub unsafe extern "C" fn readline_push_history(line: *const u8) {
    let mut n = 0;
    while *line.add(n) != 0 {
        n += 1;
    }
    let text = core::slice::from_raw_parts(line, n);
    if text.iter().all(|&b| b == b' ') {
        return;
    }
    let hist = root(R_HISTORY);
    let items = py::items(hist);
    if let Some(&first) = items.first() {
        if str_bytes(first) == text {
            return;
        }
    }
    // newest first
    mp_obj_list_append(hist, NONE);
    let items = py::items_mut(hist);
    for i in (1..items.len()).rev() {
        items[i] = items[i - 1];
    }
    items[0] = new_str(text);
    if items.len() > HISTORY_MAX {
        crate::py::list_truncate(hist, HISTORY_MAX);
    }
}

/// readline(line, prompt): what pyexec's REPL calls. 0 for Enter (the text
/// appended to `line`), or a control code (3 Ctrl-C, 4 Ctrl-D...).
#[no_mangle]
pub unsafe extern "C" fn readline(line: *mut c_void, prompt: *const u8) -> i32 {
    let mut n = 0;
    while *prompt.add(n) != 0 {
        n += 1;
    }
    let prompt = core::slice::from_raw_parts(prompt, n);
    let hook = root(R_LINE);
    if is_set(hook) {
        let mut ret = 0i32;
        let r = protect(|| {
            let res = call2(hook, new_str(prompt), new_str(b""));
            if res & 1 == 1 {
                ret = py::int(res) as i32;
            } else {
                let text = str_bytes(res);
                vstr_add_strn(line, text.as_ptr(), text.len());
                let mut z = [0u8; 512];
                let k = text.len().min(511);
                z[..k].copy_from_slice(&text[..k]);
                readline_push_history(z.as_ptr());
            }
        });
        match r {
            Ok(()) => return ret,
            Err(exc) => {
                set_root(R_LINE, NONE);
                say("\r\n[line editor failed; using the built-in one]\r\n");
                __real_mp_obj_print_exception(core::ptr::addr_of!(mp_plat_print), exc);
            }
        }
    }
    // the plain editor: type, Backspace, Enter
    crate::serial::write(prompt);
    let mut buf = [0u8; 256];
    let mut len = 0;
    loop {
        let c = mp_hal_stdin_rx_chr();
        match c {
            3 | 4 if len == 0 || c == 3 => {
                crate::serial::write(b"\r\n");
                return c;
            }
            13 | 10 => {
                crate::serial::write(b"\r\n");
                vstr_add_strn(line, buf.as_ptr(), len);
                return 0;
            }
            8 | 127 => {
                if len > 0 {
                    len -= 1;
                    crate::serial::write(b"\x08 \x08");
                }
            }
            32..=255 if len < buf.len() => {
                buf[len] = c as u8;
                len += 1;
                crate::serial::write(&[c as u8]);
            }
            _ => {}
        }
    }
}

// ---- running Python ----

/// Run a whole source file (init.py). 0 if it finished, 1 if it raised.
#[no_mangle]
pub unsafe extern "C" fn mpk_exec(name: *const u8, src: *const u8, len: usize) -> i32 {
    let mut n = 0;
    while *name.add(n) != 0 {
        n += 1;
    }
    let q = py::qstr(core::str::from_utf8_unchecked(core::slice::from_raw_parts(name, n)));
    match protect(|| {
        let lex = mp_lexer_new_from_str_len(q, src, len, 0);
        let mut tree = mp_parse(lex, 1);                  // MP_PARSE_FILE_INPUT
        let f = mp_compile(&mut tree, q, false);
        call0(f);
    }) {
        Ok(()) => 0,
        Err(exc) => {
            print_exception(exc);
            1
        }
    }
}

/// repl_exec(source, whole_file=False): run what was typed at the prompt in
/// __main__, as the REPL does (expressions print their value). Returns None,
/// or the exception it raised.
unsafe extern "C" fn repl_exec(n: usize, a: *const Obj) -> Obj {
    let a = py::args(n, a);
    let src = str_bytes(a[0]);
    let kind = if n > 1 && py::truthy(a[1]) { 1 } else { 0 };   // mp_parse_input_kind_t: FILE_INPUT 1, SINGLE_INPUT 0
    let main = mp_import_name(py::qstr("__main__"), NONE, py::new_int(0));
    let main_dict = *((main + 8) as *const Obj);                // mp_obj_module_t.globals
    let ts = tls();
    let (old_globals, old_locals) = ((*ts).dict_globals, (*ts).dict_locals);
    let q = py::qstr("<stdin>");
    let r = protect(|| {
        (*ts).dict_globals = main_dict;
        (*ts).dict_locals = main_dict;
        let lex = mp_lexer_new_from_str_len(q, src.as_ptr(), src.len(), 0);
        let mut tree = mp_parse(lex, kind);
        let f = mp_compile(&mut tree, q, true);
        mp_hal_set_interrupt_char(3);
        call0(f);
        mp_hal_set_interrupt_char(-1);
        mp_handle_pending(true);
    });
    let result = match r {
        Ok(()) => NONE,
        Err(exc) => {
            mp_hal_set_interrupt_char(-1);
            mp_handle_pending(false);
            exc
        }
    };
    (*ts).dict_globals = old_globals;
    (*ts).dict_locals = old_locals;
    result
}
pub static REPL_EXEC: py::FunVar = py::Fun::var(1, 2, repl_exec);

unsafe extern "C" fn repl_continue(src: Obj) -> Obj {
    let s = str_bytes(src);
    let mut z = [0u8; 4096];
    let k = s.len().min(4095);
    z[..k].copy_from_slice(&s[..k]);
    py::boolean(mp_repl_continue_with_input(z.as_ptr()))
}
pub static REPL_CONTINUE: py::FunFixed<py::Fn1> = py::Fun::f1(repl_continue);

unsafe extern "C" fn repl_set(f: Obj) -> Obj {
    set_root(R_REPL, f)
}
pub static REPL: py::FunFixed<py::Fn1> = py::Fun::f1(repl_set);

const PYEXEC_MODE_RAW_REPL: i32 = 1;          // pyexec_mode_kind_t: FRIENDLY_REPL = 0, RAW_REPL = 1

/// The console, until a soft reboot: the Python REPL (kernel/repl.py) if one
/// is registered, else MicroPython's own.
#[no_mangle]
pub unsafe extern "C" fn mpk_repl() {
    loop {
        let f = root(R_REPL);
        if pyexec_mode_kind == PYEXEC_MODE_RAW_REPL {
            if pyexec_raw_repl() != 0 {
                break;
            }
        } else if is_set(f) {
            let mut r = 0isize;
            match protect(|| {
                r = py::int(call0(f));
            }) {
                Ok(()) => {
                    if r == 1 {
                        pyexec_mode_kind = PYEXEC_MODE_RAW_REPL;
                        continue;
                    }
                    break;
                }
                Err(exc) => {
                    if is_keyboard_interrupt(exc) {
                        say("\r\nKeyboardInterrupt\r\n");
                        continue;
                    }
                    say("\r\nthe Python console failed; using the built-in one\r\n");
                    print_exception(exc);
                    set_root(R_REPL, NONE);
                }
            }
        } else if pyexec_friendly_repl() != 0 {
            break;
        }
    }
}

// ---- CPU faults become Python exceptions ----

const FAULT_NAMES: [&str; 20] = [
    "divide error", "debug", "NMI", "breakpoint", "overflow", "bound range", "invalid opcode",
    "device not available", "double fault", "coprocessor", "invalid TSS", "segment not present",
    "stack fault", "general protection", "page fault", "reserved", "x87 FPU error", "alignment check",
    "machine check", "SIMD FP error",
];

#[no_mangle]
pub unsafe extern "C" fn mpk_raise_fault(vector: u64, err: u64, rip: u64, cr2: u64) -> ! {
    let name = FAULT_NAMES.get(vector as usize).copied().unwrap_or("exception");
    mp_raise_msg_varg(core::ptr::addr_of!(mp_type_RuntimeError),
                      b"CPU fault %d (%.*s) err=0x%lx rip=0x%lx addr=0x%lx\0".as_ptr(),
                      vector as i32, name.len() as i32, name.as_ptr(), err, rip, cr2)
}

#[allow(dead_code)]
fn unused() {
    let _ = unsafe { core::ptr::addr_of!(mp_type_OSError) };
}
