// Runtime glue between the MicroPython VM and the Rust layer: console
// plumbing, garbage-collector roots, and the entry points Rust calls.
// This file contains no policy and no hardware access of its own.

#include <string.h>
#include <stdio.h>
#include "py/runtime.h"
#include "py/gc.h"
#include "py/mphal.h"
#include "py/stream.h"
#include "py/mpthread.h"
#include "shared/readline/readline.h"
#include "py/lexer.h"
#include "py/parse.h"
#include "py/compile.h"
#include "py/objexcept.h"
#include "shared/runtime/pyexec.h"
#include "shared/runtime/gchelper.h"
#include "shared/runtime/interrupt_char.h"
#include "py/repl.h"
#include "rk.h"

MP_REGISTER_ROOT_POINTER(mp_obj_t mpk_stdout_hook);
MP_REGISTER_ROOT_POINTER(mp_obj_t mpk_irq_handlers[256]);

void gc_collect(void) {
    gc_collect_start();
    gc_helper_collect_regs_and_stack();
    mpk_gc_other_threads();
    gc_collect_end();
}

void nlr_jump_fail(void *val) {
    rk_fatal((uint64_t)(uintptr_t)val);
}

// ---- console input ----

// One byte of console input, from whichever driver produced it.
bool mpk_async_raise(uint32_t id, mp_obj_t exc);

// Ctrl-C for the console thread. Goes through mpk_async_raise so that it
// waits while the thread is in a masked section (e.g. writing to the disk).
static void raise_kbd_interrupt(void) {
    MP_STATE_VM(mp_kbd_exception).traceback_data = NULL;
    mpk_async_raise(0, MP_OBJ_FROM_PTR(&MP_STATE_VM(mp_kbd_exception)));
}

static mp_obj_t deliver_kbd_interrupt(mp_obj_t unused) {
    raise_kbd_interrupt();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(deliver_kbd_interrupt_obj, deliver_kbd_interrupt);

void mpk_feed(int c) {
    if (c == mp_interrupt_char) {
        // Drivers call this from an interrupt handler. Raise Ctrl-C from a
        // scheduled native callback instead, so the exception lands in the
        // interrupted program and not inside the driver's Python code.
        if (!mp_sched_schedule(MP_OBJ_FROM_PTR(&deliver_kbd_interrupt_obj), mp_const_none)) {
            raise_kbd_interrupt();
        }
    } else {
        rk_stdin_push((uint8_t)c);
    }
}

MP_REGISTER_ROOT_POINTER(mp_obj_t mpk_idle_hook);

// Runs the Python idle hook (registered with _kernel.idle_hook) once, when
// the console runs out of input. It is the safe moment for housekeeping
// such as saving command history: the console thread is between commands.
// A hook that raises is unregistered.
static void run_idle_hook(void) {
    mp_obj_t hook = MP_STATE_PORT(mpk_idle_hook);
    if (hook == MP_OBJ_NULL || hook == mp_const_none) {
        return;
    }
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_call_function_0(hook);
        nlr_pop();
    } else {
        MP_STATE_PORT(mpk_idle_hook) = mp_const_none;
        mp_printf(&mp_plat_print, "\r\n[idle hook failed and was removed]\r\n");
        mp_obj_print_exception(&mp_plat_print, MP_OBJ_FROM_PTR(nlr.ret_val));
    }
}

// Block until a byte is available. While waiting the CPU sleeps, and Python
// interrupt handlers (keyboard, serial, timer, tasks) get to run.
int mp_hal_stdin_rx_chr(void) {
    bool idle_done = false;
    for (;;) {
        int c = rk_stdin_pop();
        if (c >= 0) {
            return c;
        }
        mp_handle_pending(true);
        if (!idle_done && mp_thread_get_id() == 0) {
            idle_done = true;
            run_idle_hook();
            continue;
        }
        // Rescue path: serial input works even with no Python driver loaded.
        c = rk_serial_rx();
        if (c == 0x1D) {
            extern uint8_t mpk_dbg_mask0(void);
            char b[160];
            int n = snprintf(b, sizeof(b), "\r\n[DBG sched_state=%d mask0=%d len=%d thread=%d]\r\n",
                (int)MP_STATE_VM(sched_state), (int)mpk_dbg_mask0(), (int)MP_STATE_VM(sched_len), (int)mp_thread_get_id());
            rk_serial_write(b, n);
            continue;
        }
        if (c >= 0) {
            mpk_feed(c);
            continue;
        }
        uint64_t flags = rk_irq_save();
        if (rk_stdin_empty() && MP_STATE_VM(sched_state) != MP_SCHED_PENDING) {
            // Let other threads have the VM while this one sleeps.
            MP_THREAD_GIL_EXIT();
            rk_thread_wait(flags);
            rk_irq_restore(flags);
            MP_THREAD_GIL_ENTER();
        } else {
            rk_irq_restore(flags);
        }
    }
}

uintptr_t mp_hal_stdio_poll(uintptr_t poll_flags) {
    uintptr_t ret = poll_flags & MP_STREAM_POLL_WR;
    if ((poll_flags & MP_STREAM_POLL_RD) && !rk_stdin_empty()) {
        ret |= MP_STREAM_POLL_RD;
    }
    return ret;
}

// ---- console output ----

// Output goes to the Python console driver if one is registered, else to
// the serial port. A driver that raises is unregistered, so a broken
// console can never take the system's voice away.
mp_uint_t mp_hal_stdout_tx_strn(const char *str, size_t len) {
    static bool in_hook;
    static mp_uint_t hook_owner;
    // One thread at a time drives the console; others queue up here.
    while (in_hook && hook_owner != mp_thread_get_id()) {
        MP_THREAD_GIL_EXIT();
        rk_thread_yield();
        MP_THREAD_GIL_ENTER();
    }
    mp_obj_t hook = MP_STATE_PORT(mpk_stdout_hook);
    if (hook == MP_OBJ_NULL || hook == mp_const_none || in_hook || gc_is_locked()) {
        rk_serial_write(str, len);
        return len;
    }
    in_hook = true;
    hook_owner = mp_thread_get_id();
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_call_function_1(hook, mp_obj_new_bytes((const byte *)str, len));
        nlr_pop();
        in_hook = false;
    } else {
        in_hook = false;
        mp_obj_t exc = MP_OBJ_FROM_PTR(nlr.ret_val);
        if (mp_obj_is_subclass_fast(MP_OBJ_FROM_PTR(mp_obj_get_type(exc)), MP_OBJ_FROM_PTR(&mp_type_KeyboardInterrupt))) {
            nlr_jump(nlr.ret_val);
        }
        MP_STATE_PORT(mpk_stdout_hook) = mp_const_none;
        rk_serial_write(str, len);
        static const char msg[] = "\r\n[console driver failed; output now goes to serial]\r\n";
        rk_serial_write(msg, sizeof(msg) - 1);
        mp_obj_print_exception(&mp_plat_print, exc);
    }
    return len;
}

// ---- line editor ----

MP_REGISTER_ROOT_POINTER(mp_obj_t mpk_line_hook);

void __real_mp_obj_print_exception(const mp_print_t *print, mp_obj_t exc);

// Called by readline() (mpy/readline.c) before its own C editor. If a
// Python line editor is registered (_kernel.line_editor), it reads the line:
// a str is appended to `line` and 0 is returned (Enter); an int is returned
// as a control code (Ctrl-C = 3, ...). Returns -2 when there is no Python
// editor or it failed, in which case the C editor takes over.
int mpk_line_editor(vstr_t *line, const char *prompt) {
    mp_obj_t hook = MP_STATE_PORT(mpk_line_hook);
    if (hook == MP_OBJ_NULL || hook == mp_const_none) {
        return -2;
    }
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_obj_t res = mp_call_function_2(hook, mp_obj_new_str(prompt, strlen(prompt)),
            mp_obj_new_str(line->buf, line->len));
        int ret = 0;
        if (mp_obj_is_small_int(res)) {
            ret = MP_OBJ_SMALL_INT_VALUE(res);
        } else {
            const char *text = mp_obj_str_get_str(res);
            vstr_add_str(line, text);
            readline_push_history(text);
        }
        nlr_pop();
        return ret;
    }
    MP_STATE_PORT(mpk_line_hook) = mp_const_none;
    mp_printf(&mp_plat_print, "\r\n[line editor failed; using the built-in one]\r\n");
    __real_mp_obj_print_exception(&mp_plat_print, MP_OBJ_FROM_PTR(nlr.ret_val));
    return -2;
}

// ---- exception reports ----

MP_REGISTER_ROOT_POINTER(mp_obj_t mpk_exc_hook);

// The linker routes every call to mp_obj_print_exception here (see
// .cargo/config.toml). Reports headed for the console -- errors at the >>>
// prompt, uncaught errors in threads -- go to the Python hook registered
// with _kernel.exc_hook, which adds source lines. Everything else, or a
// hook that fails, uses MicroPython's own printer.
void __wrap_mp_obj_print_exception(const mp_print_t *print, mp_obj_t exc) {
    static bool busy;
    mp_obj_t hook = MP_STATE_PORT(mpk_exc_hook);
    if (print != &mp_plat_print || busy || hook == MP_OBJ_NULL || hook == mp_const_none || gc_is_locked()) {
        __real_mp_obj_print_exception(print, exc);
        return;
    }
    busy = true;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_call_function_1(hook, exc);
        nlr_pop();
    } else {
        MP_STATE_PORT(mpk_exc_hook) = mp_const_none;
        __real_mp_obj_print_exception(print, exc);
    }
    busy = false;
}

// ---- entry points called from Rust ----

// mp_cstack_init_with_top is inline in the MicroPython headers, so Rust
// reaches it through this exported wrapper.
void mpk_cstack_init(void *top, size_t size) {
    mp_thread_set_state(&mp_state_ctx.thread);   // we are the main thread
    mp_cstack_init_with_top(top, size);
}

void mpk_init(void) {
    // The history array points into the Python heap, which was just
    // re-created: forget the old entries (they would dangle after Ctrl-D).
    readline_init0();
    MP_STATE_PORT(mpk_stdout_hook) = mp_const_none;
    MP_STATE_PORT(mpk_idle_hook) = mp_const_none;
    MP_STATE_PORT(mpk_exc_hook) = mp_const_none;
    MP_STATE_PORT(mpk_line_hook) = mp_const_none;
    MP_STATE_PORT(mpk_repl_fn) = mp_const_none;
    for (uint32_t i = 0; i < 32; i++) {
        mpk_async_reset(i);
    }
    for (size_t i = 0; i < 256; i++) {
        MP_STATE_PORT(mpk_irq_handlers)[i] = mp_const_none;
    }
}

// Compile and run Python source held in memory, in the __main__ namespace.
int mpk_exec(const char *name, const char *src, size_t len) {
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_lexer_t *lex = mp_lexer_new_from_str_len(qstr_from_str(name), src, len, 0);
        qstr source_name = lex->source_name;
        mp_parse_tree_t parse_tree = mp_parse(lex, MP_PARSE_FILE_INPUT);
        mp_obj_t module_fun = mp_compile(&parse_tree, source_name, false);
        mp_call_function_0(module_fun);
        nlr_pop();
        return 0;
    }
    mp_obj_print_exception(&mp_plat_print, MP_OBJ_FROM_PTR(nlr.ret_val));
    return 1;
}

// ---- the interactive console ----
//
// The console loop itself is Python (kernel/repl.py, registered with
// _kernel.repl(fn)); fn() returns 0 to soft-reboot, 1 for the raw REPL.
// These two helpers give it what MicroPython's own REPL uses internally.
MP_REGISTER_ROOT_POINTER(mp_obj_t mpk_repl_fn);

// repl_continue(src) -> True if `src` is an unfinished statement.
static mp_obj_t k_repl_continue(mp_obj_t src) {
    return mp_obj_new_bool(mp_repl_continue_with_input(mp_obj_str_get_str(src)));
}
MP_DEFINE_CONST_FUN_OBJ_1(mpk_repl_continue_obj, k_repl_continue);

// repl_exec(src, whole_file=False) -> None, or the exception it raised.
// Compiles `src` as interactive input ("single": expression values are
// shown; whole_file: any number of statements, as pasted) and runs it in
// __main__, with Ctrl-C enabled. The exception is caught here, in C, so
// its traceback holds only the user's frames.
static mp_obj_t k_repl_exec(size_t n_args, const mp_obj_t *args) {
    size_t len;
    const char *src = mp_obj_str_get_data(args[0], &len);
    mp_parse_input_kind_t kind = n_args > 1 && mp_obj_is_true(args[1])
        ? MP_PARSE_FILE_INPUT : MP_PARSE_SINGLE_INPUT;
    mp_obj_dict_t *old_globals = mp_globals_get();
    mp_obj_dict_t *old_locals = mp_locals_get();
    mp_obj_t result = mp_const_none;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_globals_set(&MP_STATE_VM(dict_main));
        mp_locals_set(&MP_STATE_VM(dict_main));
        mp_lexer_t *lex = mp_lexer_new_from_str_len(MP_QSTR__lt_stdin_gt_, src, len, 0);
        qstr source_name = lex->source_name;
        mp_parse_tree_t parse_tree = mp_parse(lex, kind);
        mp_obj_t fun = mp_compile(&parse_tree, source_name, true);
        mp_hal_set_interrupt_char(3);
        mp_call_function_0(fun);
        mp_hal_set_interrupt_char(-1);
        mp_handle_pending(true);
        nlr_pop();
    } else {
        mp_hal_set_interrupt_char(-1);
        mp_handle_pending(false);
        result = MP_OBJ_FROM_PTR(nlr.ret_val);
    }
    mp_globals_set(old_globals);
    mp_locals_set(old_locals);
    return result;
}
MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mpk_repl_exec_obj, 1, 2, k_repl_exec);

// repl(fn_or_None) -> previous: the console loop to run.
static mp_obj_t k_repl(mp_obj_t fn) {
    mp_obj_t old = MP_STATE_PORT(mpk_repl_fn);
    MP_STATE_PORT(mpk_repl_fn) = fn;
    return old;
}
MP_DEFINE_CONST_FUN_OBJ_1(mpk_repl_obj, k_repl);

// Run the console until a soft reboot is requested. If the Python console
// fails, MicroPython's built-in one takes over.
void mpk_repl(void) {
    for (;;) {
        mp_obj_t fn = MP_STATE_PORT(mpk_repl_fn);
        if (pyexec_mode_kind == PYEXEC_MODE_RAW_REPL) {
            if (pyexec_raw_repl() != 0) {
                break;
            }
        } else if (fn != mp_const_none && fn != MP_OBJ_NULL) {
            mp_int_t r = 0;
            nlr_buf_t nlr;
            if (nlr_push(&nlr) == 0) {
                r = mp_obj_get_int(mp_call_function_0(fn));
                nlr_pop();
            } else {
                mp_obj_t exc = MP_OBJ_FROM_PTR(nlr.ret_val);
                if (mp_obj_is_subclass_fast(MP_OBJ_FROM_PTR(mp_obj_get_type(exc)),
                    MP_OBJ_FROM_PTR(&mp_type_KeyboardInterrupt))) {
                    mp_hal_stdout_tx_str("\r\nKeyboardInterrupt\r\n");
                    continue;
                }
                mp_hal_stdout_tx_str("\r\nthe Python console failed; using the built-in one\r\n");
                mp_obj_print_exception(&mp_plat_print, exc);
                MP_STATE_PORT(mpk_repl_fn) = mp_const_none;
                continue;
            }
            if (r == 1) {
                pyexec_mode_kind = PYEXEC_MODE_RAW_REPL;
                continue;
            }
            break;
        } else {
            if (pyexec_friendly_repl() != 0) {
                break;
            }
        }
    }
}

static const char *const fault_names[] = {
    "divide error", "debug", "NMI", "breakpoint", "overflow", "bound range",
    "invalid opcode", "device not available", "double fault", "coprocessor",
    "invalid TSS", "segment not present", "stack fault", "general protection",
    "page fault", "reserved", "x87 FPU error", "alignment check",
    "machine check", "SIMD FP error",
};

// A CPU exception happened while Python was running: surface it as a
// Python exception instead of taking the machine down.
void mpk_raise_fault(uint64_t vector, uint64_t err, uint64_t rip, uint64_t cr2) {
    const char *name = vector < MP_ARRAY_SIZE(fault_names) ? fault_names[vector] : "exception";
    mp_raise_msg_varg(&mp_type_RuntimeError,
        MP_ERROR_TEXT("CPU fault %d (%s) err=0x%lx rip=0x%lx addr=0x%lx"),
        (int)vector, name, (unsigned long)err, (unsigned long)rip, (unsigned long)cr2);
}
