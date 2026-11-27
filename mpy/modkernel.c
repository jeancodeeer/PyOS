// The `_kernel` module: Python bindings for the Rust primitives.
// Pure argument marshalling; every function forwards to rust/*.rs.

#include "py/runtime.h"
#include "py/gc.h"
#include "py/mphal.h"
#include "py/objstr.h"
#include "py/mpthread.h"
#include "shared/readline/readline.h"
#include <string.h>
#include "rk.h"

#define U64(o) ((uint64_t)mp_obj_get_int_truncated(o))
#define NEW_U64(v) mp_obj_new_int_from_ull(v)

// ---- port I/O ----
static mp_obj_t k_inb(mp_obj_t p) {
    return MP_OBJ_NEW_SMALL_INT(rk_inb(mp_obj_get_int(p)));
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_inb_obj, k_inb);
static mp_obj_t k_inw(mp_obj_t p) {
    return MP_OBJ_NEW_SMALL_INT(rk_inw(mp_obj_get_int(p)));
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_inw_obj, k_inw);
static mp_obj_t k_inl(mp_obj_t p) {
    return NEW_U64(rk_inl(mp_obj_get_int(p)));
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_inl_obj, k_inl);
static mp_obj_t k_outb(mp_obj_t p, mp_obj_t v) {
    rk_outb(mp_obj_get_int(p), mp_obj_get_int(v));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_outb_obj, k_outb);
static mp_obj_t k_outw(mp_obj_t p, mp_obj_t v) {
    rk_outw(mp_obj_get_int(p), mp_obj_get_int(v));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_outw_obj, k_outw);
static mp_obj_t k_outl(mp_obj_t p, mp_obj_t v) {
    rk_outl(mp_obj_get_int(p), (uint32_t)U64(v));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_outl_obj, k_outl);

// insw(port, buf) fills buf with 16-bit words read from port; outsw writes.
static mp_obj_t k_insw(mp_obj_t p, mp_obj_t buf) {
    mp_buffer_info_t b;
    mp_get_buffer_raise(buf, &b, MP_BUFFER_WRITE);
    rk_insw(mp_obj_get_int(p), b.buf, b.len / 2);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_insw_obj, k_insw);
static mp_obj_t k_outsw(mp_obj_t p, mp_obj_t buf) {
    mp_buffer_info_t b;
    mp_get_buffer_raise(buf, &b, MP_BUFFER_READ);
    rk_outsw(mp_obj_get_int(p), b.buf, b.len / 2);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_outsw_obj, k_outsw);

// ---- CPU ----
static mp_obj_t k_irq_disable(void) {
    return mp_obj_new_bool(rk_irq_save() & 0x200);
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_irq_disable_obj, k_irq_disable);
static mp_obj_t k_irq_enable(void) {
    rk_sti();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_irq_enable_obj, k_irq_enable);
static mp_obj_t k_hlt(void) {
    rk_hlt();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_hlt_obj, k_hlt);
// wait(): sleep until the next interrupt (enabling interrupts). Other
// threads run meanwhile; the CPU halts only when none can.
static mp_obj_t k_wait(void) {
    MP_THREAD_GIL_EXIT();
    rk_irq_save();
    rk_thread_wait(0x200);
    MP_THREAD_GIL_ENTER();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_wait_obj, k_wait);
static mp_obj_t k_rdmsr(mp_obj_t msr) {
    return NEW_U64(rk_rdmsr((uint32_t)U64(msr)));
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_rdmsr_obj, k_rdmsr);
static mp_obj_t k_wrmsr(mp_obj_t msr, mp_obj_t v) {
    rk_wrmsr((uint32_t)U64(msr), U64(v));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_wrmsr_obj, k_wrmsr);
static mp_obj_t k_cpuid(size_t n, const mp_obj_t *args) {
    uint32_t r[4];
    rk_cpuid((uint32_t)U64(args[0]), n > 1 ? (uint32_t)U64(args[1]) : 0, r);
    mp_obj_t t[4] = { NEW_U64(r[0]), NEW_U64(r[1]), NEW_U64(r[2]), NEW_U64(r[3]) };
    return mp_obj_new_tuple(4, t);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(k_cpuid_obj, 1, 2, k_cpuid);
static mp_obj_t k_rdtsc(void) {
    return NEW_U64(rk_rdtsc());
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_rdtsc_obj, k_rdtsc);
// cr(n) reads control register n; cr(n, value) writes it.
static mp_obj_t k_cr(size_t n, const mp_obj_t *args) {
    uint32_t reg = mp_obj_get_int(args[0]);
    if (!(reg == 0 || reg == 2 || reg == 3 || reg == 4 || reg == 8)) {
        mp_raise_ValueError(MP_ERROR_TEXT("no such control register"));
    }
    if (n == 1) {
        return NEW_U64(rk_read_cr(reg));
    }
    rk_write_cr(reg, U64(args[1]));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(k_cr_obj, 1, 2, k_cr);
static mp_obj_t k_invlpg(mp_obj_t a) {
    rk_invlpg(U64(a));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_invlpg_obj, k_invlpg);
// call(addr, *args): run machine code at addr (System V ABI, <= 6 int args).
static mp_obj_t k_call(size_t n, const mp_obj_t *args) {
    uint64_t a[6] = {0};
    for (size_t i = 1; i < n; i++) {
        a[i - 1] = U64(args[i]);
    }
    return NEW_U64(rk_call(U64(args[0]), a[0], a[1], a[2], a[3], a[4], a[5]));
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(k_call_obj, 1, 7, k_call);

// ---- interrupts ----
// irq_handler(vector, fn_or_None) -> previous handler. fn(vector) runs on
// the VM scheduler shortly after the interrupt fires.
static mp_obj_t k_irq_handler(mp_obj_t vec, mp_obj_t fn) {
    mp_uint_t v = mp_obj_get_int(vec);
    if (v > 255) {
        mp_raise_ValueError(MP_ERROR_TEXT("vector out of range"));
    }
    mp_obj_t old = MP_STATE_PORT(mpk_irq_handlers)[v];
    rk_irq_arm(v, false);
    MP_STATE_PORT(mpk_irq_handlers)[v] = fn;
    rk_irq_ack(v);
    rk_irq_arm(v, fn != mp_const_none);
    return old;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_irq_handler_obj, k_irq_handler);
static mp_obj_t k_irq_count(mp_obj_t vec) {
    return NEW_U64(rk_irq_count(mp_obj_get_int(vec)));
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_irq_count_obj, k_irq_count);
static mp_obj_t k_irq_dropped(void) {
    return NEW_U64(rk_irq_dropped());
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_irq_dropped_obj, k_irq_dropped);

// irq_fifo(vector, status_port, mask, value, data_port): at interrupt time,
// while inb(status) & mask == value, queue inb(data). mask 0 stops it. irq_read(vector)
// returns the queued bytes; irq_lost() counts bytes dropped on overflow.
static mp_obj_t k_irq_fifo(size_t n_args, const mp_obj_t *args) {
    bool ok = rk_irq_fifo(mp_obj_get_int(args[0]), mp_obj_get_int(args[1]),
        mp_obj_get_int(args[2]), mp_obj_get_int(args[3]), mp_obj_get_int(args[4]));
    if (!ok) {
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("no free irq fifo"));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(k_irq_fifo_obj, 5, 5, k_irq_fifo);
static mp_obj_t k_irq_read(mp_obj_t vec) {
    uint8_t buf[256];
    size_t n = rk_irq_fifo_read(mp_obj_get_int(vec), buf, sizeof(buf));
    return mp_obj_new_bytes(buf, n);
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_irq_read_obj, k_irq_read);
static mp_obj_t k_irq_lost(void) {
    return NEW_U64(rk_irq_fifo_lost());
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_irq_lost_obj, k_irq_lost);

static mp_obj_t k_dispatch(mp_obj_t vec) {
    mp_uint_t v = mp_obj_get_int(vec) & 0xFF;
    rk_irq_ack(v);
    mp_obj_t fn = MP_STATE_PORT(mpk_irq_handlers)[v];
    if (fn != mp_const_none && fn != MP_OBJ_NULL) {
        mp_call_function_1(fn, vec);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_dispatch_obj, k_dispatch);

// Called by the Rust interrupt dispatcher, in interrupt context.
bool mpk_schedule_irq(uint32_t vector) {
    return mp_sched_schedule(MP_OBJ_FROM_PTR(&k_dispatch_obj), MP_OBJ_NEW_SMALL_INT(vector));
}

// ---- threads ----
// preempt(vector, ticks): switch threads every `ticks` interrupts on
// `vector` (the system timer). ticks=0 turns preemption off.
static mp_obj_t k_preempt(mp_obj_t vec, mp_obj_t ticks) {
    rk_preempt(mp_obj_get_int(vec), mp_obj_get_int(ticks));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_preempt_obj, k_preempt);
// threads() -> [(id, state, ticks, switches)]; state 1 ready, 2 asleep, 3 running.
static mp_obj_t k_threads(void) {
    mp_obj_t list = mp_obj_new_list(0, NULL);
    for (uint32_t i = 0; i < 32; i++) {
        uint64_t v[3];
        if (rk_thread_info(i, v)) {
            mp_obj_t t[4] = { MP_OBJ_NEW_SMALL_INT(i), MP_OBJ_NEW_SMALL_INT(v[0]), NEW_U64(v[1]), NEW_U64(v[2]) };
            mp_obj_list_append(list, mp_obj_new_tuple(4, t));
        }
    }
    return list;
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_threads_obj, k_threads);

static uint8_t async_mask[32];
MP_REGISTER_ROOT_POINTER(mp_obj_t mpk_async_deferred[32]);

void mpk_async_reset(uint32_t id) {
    async_mask[id & 31] = 0;
    MP_STATE_PORT(mpk_async_deferred)[id & 31] = MP_OBJ_NULL;
}

// A thread is ending: drop any mask it still holds, so the scheduler lock it
// took is not left behind.
void mpk_async_exit(uint32_t id) {
    id &= 31;
    if (async_mask[id]) {
        async_mask[id] = 0;
        mp_sched_unlock();
    }
    MP_STATE_PORT(mpk_async_deferred)[id] = MP_OBJ_NULL;
}

// Deliver an exception to a thread from outside it: now, or when the thread
// lifts its mask (see thread_mask).
bool mpk_async_raise(uint32_t id, mp_obj_t exc) {
    if (id >= 32) {
        return false;
    }
    mp_state_thread_t *ts = (mp_state_thread_t *)(uintptr_t)rk_thread_tls(id);
    if (ts == NULL) {
        return false;
    }
    if (async_mask[id]) {
        MP_STATE_PORT(mpk_async_deferred)[id] = exc;
    } else {
        ts->mp_pending_exception = exc;
    }
    return true;
}

// thread_raise(id, exc): make thread `id` raise `exc` (a type or instance)
// at its next bytecode boundary. Used for kill and per-thread Ctrl-C.
static mp_obj_t k_thread_raise(mp_obj_t id_in, mp_obj_t exc) {
    if (mp_obj_is_exception_type(exc)) {
        exc = mp_obj_new_exception(MP_OBJ_TO_PTR(exc));
    } else if (!mp_obj_is_exception_instance(exc)) {
        mp_raise_TypeError(MP_ERROR_TEXT("exceptions must derive from BaseException"));
    }
    if (!mpk_async_raise(mp_obj_get_int(id_in), exc)) {
        mp_raise_ValueError(MP_ERROR_TEXT("no such thread"));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_thread_raise_obj, k_thread_raise);

// thread_mask(True/False): while masked, the calling thread cannot be hit by
// an exception from outside (kill, thread.interrupt, Ctrl-C); it is held and
// raised when the mask is lifted. Interrupt handlers and tasks are held back
// too (they could otherwise run on this very thread, in the middle of its
// operation); other threads keep running. Used around operations that must
// not be abandoned half-way, such as a filesystem update. Calls nest.
static mp_obj_t k_thread_mask(mp_obj_t on) {
    uint32_t id = rk_thread_current() & 31;
    if (mp_obj_is_true(on)) {
        if (async_mask[id]++ == 0) {
            mp_sched_lock();
        }
    } else if (async_mask[id] && --async_mask[id] == 0) {
        mp_sched_unlock();
        mp_obj_t exc = MP_STATE_PORT(mpk_async_deferred)[id];
        if (exc != MP_OBJ_NULL) {
            // Raised right here, as the protected operation ends.
            MP_STATE_PORT(mpk_async_deferred)[id] = MP_OBJ_NULL;
            nlr_raise(exc);
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_thread_mask_obj, k_thread_mask);

// ---- console history (the arrays belong to shared/readline) ----
// history() -> list of past input lines, newest first.
static mp_obj_t k_history(void) {
    mp_obj_t list = mp_obj_new_list(0, NULL);
    for (size_t i = 0; i < MICROPY_READLINE_HISTORY_SIZE; i++) {
        const char *line = MP_STATE_PORT(readline_hist)[i];
        if (line == NULL) {
            break;
        }
        mp_obj_list_append(list, mp_obj_new_str(line, strlen(line)));
    }
    return list;
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_history_obj, k_history);
static mp_obj_t k_history_add(mp_obj_t line) {
    readline_push_history(mp_obj_str_get_str(line));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_history_add_obj, k_history_add);
// idle_hook(fn_or_None) -> previous. fn() runs when the console waits for input.
static mp_obj_t k_idle_hook(mp_obj_t fn) {
    mp_obj_t old = MP_STATE_PORT(mpk_idle_hook);
    MP_STATE_PORT(mpk_idle_hook) = fn;
    return old;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_idle_hook_obj, k_idle_hook);
// exc_hook(fn_or_None) -> previous. fn(exc) prints exceptions reported to the console.
static mp_obj_t k_exc_hook(mp_obj_t fn) {
    mp_obj_t old = MP_STATE_PORT(mpk_exc_hook);
    MP_STATE_PORT(mpk_exc_hook) = fn;
    return old;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_exc_hook_obj, k_exc_hook);
extern const mp_obj_fun_builtin_fixed_t mpk_repl_obj, mpk_repl_continue_obj;
extern const mp_obj_fun_builtin_var_t mpk_repl_exec_obj;

// line_editor(fn_or_None) -> previous. fn(prompt, text_so_far) reads one line
// of console input and returns it (str), or a control code (int).
static mp_obj_t k_line_editor(mp_obj_t fn) {
    mp_obj_t old = MP_STATE_PORT(mpk_line_hook);
    MP_STATE_PORT(mpk_line_hook) = fn;
    return old;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_line_editor_obj, k_line_editor);
// stdin_pending() -> True if console input is waiting to be read.
static mp_obj_t k_stdin_pending(void) {
    return mp_obj_new_bool(!rk_stdin_empty());
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_stdin_pending_obj, k_stdin_pending);
// klog() -> bytes: what the Rust layer has logged since power-on (last 8 KiB).
static mp_obj_t k_klog(void) {
    vstr_t v;
    vstr_init_len(&v, 8192);
    v.len = rk_klog((uint8_t *)v.buf, v.len);
    return mp_obj_new_bytes_from_vstr(&v);
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_klog_obj, k_klog);

// ---- console ----
// stdin_push(int | bytes): feed console input (what a keyboard driver calls).
static mp_obj_t k_stdin_push(mp_obj_t o) {
    if (mp_obj_is_int(o)) {
        mpk_feed(mp_obj_get_int(o) & 0xFF);
    } else {
        mp_buffer_info_t b;
        mp_get_buffer_raise(o, &b, MP_BUFFER_READ);
        for (size_t i = 0; i < b.len; i++) {
            mpk_feed(((const uint8_t *)b.buf)[i]);
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_stdin_push_obj, k_stdin_push);
// stdout_hook(fn_or_None) -> previous. fn(bytes) receives all console output.
static mp_obj_t k_stdout_hook(mp_obj_t fn) {
    mp_obj_t old = MP_STATE_PORT(mpk_stdout_hook);
    MP_STATE_PORT(mpk_stdout_hook) = fn;
    return old;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_stdout_hook_obj, k_stdout_hook);
static mp_obj_t k_serial_write(mp_obj_t o) {
    mp_buffer_info_t b;
    mp_get_buffer_raise(o, &b, MP_BUFFER_READ);
    rk_serial_write(b.buf, b.len);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(k_serial_write_obj, k_serial_write);

// ---- memory ----
static mp_obj_t k_info(void) {
    static const qstr names[] = {
        MP_QSTR_kernel_start, MP_QSTR_kernel_end, MP_QSTR_heap_start, MP_QSTR_heap_end,
        MP_QSTR_multiboot, MP_QSTR_initrd_start, MP_QSTR_initrd_end,
        MP_QSTR_stack_base, MP_QSTR_stack_top, MP_QSTR_idt, MP_QSTR_boots,
        MP_QSTR_pool_start, MP_QSTR_pool_end,
        // ARM64 (see rust/main.rs, mod I): 0 on PCs
        MP_QSTR_arch, MP_QSTR_fb_addr, MP_QSTR_fb_width, MP_QSTR_fb_height, MP_QSTR_fb_pitch,
        MP_QSTR_fb_format, MP_QSTR_rsdp, MP_QSTR_epoch, MP_QSTR_ecam, MP_QSTR_pio, MP_QSTR_psci,
        MP_QSTR_timer_hz, MP_QSTR_mmap, MP_QSTR_mmap_size, MP_QSTR_mmap_desc, MP_QSTR_timer_irq,
    };
    mp_obj_t d = mp_obj_new_dict(MP_ARRAY_SIZE(names));
    for (size_t i = 0; i < MP_ARRAY_SIZE(names); i++) {
        mp_obj_dict_store(d, MP_OBJ_NEW_QSTR(names[i]), NEW_U64(rk_info(i)));
    }
    return d;
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_info_obj, k_info);
// ---- the heap's reserve ----
// rust/main.rs sets aside a big piece of RAM at boot (info "pool_start" ..
// "pool_end"). When the Python heap is full, MicroPython itself asks for
// more (MICROPY_GC_SPLIT_HEAP_AUTO): mpk_heap_alloc() hands out a piece of
// the reserve, and mpk_heap_free() takes back a piece the heap emptied.
#define POOL_SLOTS 64
static uintptr_t free_at[POOL_SLOTS], free_len[POOL_SLOTS];   // free pieces of the reserve
static uintptr_t used_at[POOL_SLOTS], used_len[POOL_SLOTS];   // pieces lent to the heap
static int n_free = -1, n_used = 0;

static void pool_init(void) {
    n_free = 0;
    uintptr_t s = rk_info(11), e = rk_info(12);
    if (e > s) {
        free_at[0] = s;
        free_len[0] = e - s;
        n_free = 1;
    }
}

void *mpk_heap_alloc(size_t size) {
    if (n_free < 0) {
        pool_init();
    }
    size = (size + 4095) & ~(size_t)4095;
    if (n_used >= POOL_SLOTS) {
        return NULL;
    }
    for (int i = 0; i < n_free; i++) {
        if (free_len[i] >= size) {
            uintptr_t p = free_at[i];
            free_at[i] += size;
            free_len[i] -= size;
            used_at[n_used] = p;
            used_len[n_used++] = size;
            return (void *)p;
        }
    }
    return NULL;
}

void mpk_heap_free(void *ptr) {
    uintptr_t p = (uintptr_t)ptr;
    for (int i = 0; i < n_used; i++) {
        if (used_at[i] == p) {
            uintptr_t len = used_len[i];
            used_at[i] = used_at[n_used - 1];
            used_len[i] = used_len[--n_used];
            for (int k = 0; k < n_free; k++) {          // join a free neighbour
                if (free_at[k] + free_len[k] == p) {
                    free_len[k] += len;
                    return;
                }
                if (p + len == free_at[k]) {
                    free_at[k] = p;
                    free_len[k] += len;
                    return;
                }
            }
            if (n_free < POOL_SLOTS) {
                free_at[n_free] = p;
                free_len[n_free++] = len;
            }
            return;
        }
    }
    // not from the reserve (added with heap_add): it stays with kernel/mm.py
}

size_t gc_get_max_new_split(void) {
    if (n_free < 0) {
        pool_init();
    }
    size_t best = 0;
    for (int i = 0; i < n_free; i++) {
        if (free_len[i] > best) {
            best = free_len[i];
        }
    }
    return best;
}

// heap_pool() -> (reserve size, free in it): for memory statistics.
static mp_obj_t k_heap_pool(void) {
    if (n_free < 0) {
        pool_init();
    }
    uintptr_t free = 0;
    for (int i = 0; i < n_free; i++) {
        free += free_len[i];
    }
    mp_obj_t t[2] = { NEW_U64(rk_info(12) - rk_info(11)), NEW_U64(free) };
    return mp_obj_new_tuple(2, t);
}
static MP_DEFINE_CONST_FUN_OBJ_0(k_heap_pool_obj, k_heap_pool);

// heap_add(addr, size): give the Python heap another block of RAM.
static mp_obj_t k_heap_add(mp_obj_t addr, mp_obj_t size) {
    uintptr_t a = U64(addr);
    gc_add((void *)a, (void *)(a + U64(size)));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(k_heap_add_obj, k_heap_add);

static const mp_rom_map_elem_t kernel_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__kernel) },
    { MP_ROM_QSTR(MP_QSTR_inb), MP_ROM_PTR(&k_inb_obj) },
    { MP_ROM_QSTR(MP_QSTR_inw), MP_ROM_PTR(&k_inw_obj) },
    { MP_ROM_QSTR(MP_QSTR_inl), MP_ROM_PTR(&k_inl_obj) },
    { MP_ROM_QSTR(MP_QSTR_outb), MP_ROM_PTR(&k_outb_obj) },
    { MP_ROM_QSTR(MP_QSTR_outw), MP_ROM_PTR(&k_outw_obj) },
    { MP_ROM_QSTR(MP_QSTR_outl), MP_ROM_PTR(&k_outl_obj) },
    { MP_ROM_QSTR(MP_QSTR_insw), MP_ROM_PTR(&k_insw_obj) },
    { MP_ROM_QSTR(MP_QSTR_outsw), MP_ROM_PTR(&k_outsw_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq_fifo), MP_ROM_PTR(&k_irq_fifo_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq_read), MP_ROM_PTR(&k_irq_read_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq_lost), MP_ROM_PTR(&k_irq_lost_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq_disable),MP_ROM_PTR(&k_irq_disable_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq_enable), MP_ROM_PTR(&k_irq_enable_obj) },
    { MP_ROM_QSTR(MP_QSTR_hlt), MP_ROM_PTR(&k_hlt_obj) },
    { MP_ROM_QSTR(MP_QSTR_wait), MP_ROM_PTR(&k_wait_obj) },
    { MP_ROM_QSTR(MP_QSTR_rdmsr), MP_ROM_PTR(&k_rdmsr_obj) },
    { MP_ROM_QSTR(MP_QSTR_wrmsr), MP_ROM_PTR(&k_wrmsr_obj) },
    { MP_ROM_QSTR(MP_QSTR_cpuid), MP_ROM_PTR(&k_cpuid_obj) },
    { MP_ROM_QSTR(MP_QSTR_rdtsc), MP_ROM_PTR(&k_rdtsc_obj) },
    { MP_ROM_QSTR(MP_QSTR_cr), MP_ROM_PTR(&k_cr_obj) },
    { MP_ROM_QSTR(MP_QSTR_invlpg), MP_ROM_PTR(&k_invlpg_obj) },
    { MP_ROM_QSTR(MP_QSTR_call), MP_ROM_PTR(&k_call_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq_handler), MP_ROM_PTR(&k_irq_handler_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq_count), MP_ROM_PTR(&k_irq_count_obj) },
    { MP_ROM_QSTR(MP_QSTR_irq_dropped), MP_ROM_PTR(&k_irq_dropped_obj) },
    { MP_ROM_QSTR(MP_QSTR_preempt), MP_ROM_PTR(&k_preempt_obj) },
    { MP_ROM_QSTR(MP_QSTR_thread_raise), MP_ROM_PTR(&k_thread_raise_obj) },
    { MP_ROM_QSTR(MP_QSTR_thread_mask), MP_ROM_PTR(&k_thread_mask_obj) },
    { MP_ROM_QSTR(MP_QSTR_line_editor), MP_ROM_PTR(&k_line_editor_obj) },
    { MP_ROM_QSTR(MP_QSTR_repl), MP_ROM_PTR(&mpk_repl_obj) },
    { MP_ROM_QSTR(MP_QSTR_repl_exec), MP_ROM_PTR(&mpk_repl_exec_obj) },
    { MP_ROM_QSTR(MP_QSTR_repl_continue), MP_ROM_PTR(&mpk_repl_continue_obj) },
    { MP_ROM_QSTR(MP_QSTR_stdin_pending), MP_ROM_PTR(&k_stdin_pending_obj) },
    { MP_ROM_QSTR(MP_QSTR_history), MP_ROM_PTR(&k_history_obj) },
    { MP_ROM_QSTR(MP_QSTR_history_add), MP_ROM_PTR(&k_history_add_obj) },
    { MP_ROM_QSTR(MP_QSTR_idle_hook), MP_ROM_PTR(&k_idle_hook_obj) },
    { MP_ROM_QSTR(MP_QSTR_klog), MP_ROM_PTR(&k_klog_obj) },
    { MP_ROM_QSTR(MP_QSTR_exc_hook), MP_ROM_PTR(&k_exc_hook_obj) },
    { MP_ROM_QSTR(MP_QSTR_threads), MP_ROM_PTR(&k_threads_obj) },
    { MP_ROM_QSTR(MP_QSTR_stdin_push), MP_ROM_PTR(&k_stdin_push_obj) },
    { MP_ROM_QSTR(MP_QSTR_stdout_hook), MP_ROM_PTR(&k_stdout_hook_obj) },
    { MP_ROM_QSTR(MP_QSTR_serial_write), MP_ROM_PTR(&k_serial_write_obj) },
    { MP_ROM_QSTR(MP_QSTR_info), MP_ROM_PTR(&k_info_obj) },
    { MP_ROM_QSTR(MP_QSTR_heap_add), MP_ROM_PTR(&k_heap_add_obj) },
    { MP_ROM_QSTR(MP_QSTR_heap_pool), MP_ROM_PTR(&k_heap_pool_obj) },
};
static MP_DEFINE_CONST_DICT(kernel_globals, kernel_globals_table);

const mp_obj_module_t mp_module__kernel = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&kernel_globals,
};
MP_REGISTER_MODULE(MP_QSTR__kernel, mp_module__kernel);
