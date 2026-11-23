// MicroPython's thread interface, implemented on the Rust scheduler.
// The Python-facing API is the standard `_thread` module.

#include "py/runtime.h"
#include "py/gc.h"
#include "py/mpthread.h"
#include "rk.h"

#define MPK_MAX_THREADS (32)
#define MPK_STACK_DEFAULT (128 * 1024)
#define MPK_STACK_MIN (32 * 1024)

// Stacks live in the Python heap; this keeps them alive while in use.
MP_REGISTER_ROOT_POINTER(void *mpk_thread_stacks[32]);

// The VM's per-thread state. Rust swaps this on every context switch.
mp_state_thread_t *mpk_tls;

mp_state_thread_t *mp_thread_get_state(void) {
    return mpk_tls;
}

void mp_thread_set_state(mp_state_thread_t *state) {
    mpk_tls = state;
}

mp_uint_t mp_thread_get_id(void) {
    return rk_thread_current();
}

void mp_thread_start(void) {
}

void mp_thread_finish(void) {
}

typedef struct {
    void *(*entry)(void *);
    void *arg;
} launch_t;

static void thread_main(void *p) {
    launch_t *launch = p;
    launch->entry(launch->arg);
    mpk_async_exit(rk_thread_current());
    // Interrupts stay off from here to the final switch, so nothing can
    // collect this stack while it is still being stood on.
    rk_cli();
    MP_STATE_VM(mpk_thread_stacks)[rk_thread_current()] = NULL;
    rk_thread_exit();
}

mp_uint_t mp_thread_create(void *(*entry)(void *), void *arg, size_t *stack_size) {
    if (*stack_size == 0) {
        *stack_size = MPK_STACK_DEFAULT;
    } else if (*stack_size < MPK_STACK_MIN) {
        *stack_size = MPK_STACK_MIN;
    }
    uint8_t *stack = m_new(uint8_t, *stack_size);
    launch_t *launch = (launch_t *)stack;   // parked at the unused low end
    launch->entry = entry;
    launch->arg = arg;
    int id = rk_thread_create((uintptr_t)thread_main, (uintptr_t)launch,
        (uintptr_t)stack + 64, *stack_size - 64);
    if (id < 0) {
        m_del(uint8_t, stack, *stack_size);
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("too many threads"));
    }
    MP_STATE_VM(mpk_thread_stacks)[id] = stack;
    mpk_async_reset(id);
    *stack_size -= 8 * 1024;                // headroom for the stack-overflow check
    return id;
}

// The collector must see what switched-out threads hold on their stacks.
void mpk_gc_other_threads(void) {
    for (uint32_t i = 0; i < MPK_MAX_THREADS; i++) {
        uint64_t sp, top;
        if (rk_thread_stack(i, &sp, &top)) {
            gc_collect_root((void **)(uintptr_t)sp, (top - sp) / sizeof(void *));
        }
    }
}

void mp_thread_mutex_init(mp_thread_mutex_t *m) {
    m->locked = 0;
    m->waiters = 0;
}

int mp_thread_mutex_lock(mp_thread_mutex_t *m, int wait) {
    if (!__atomic_exchange_n(&m->locked, 1, __ATOMIC_SEQ_CST)) {
        return 1;
    }
    if (!wait) {
        return 0;
    }
    __atomic_add_fetch(&m->waiters, 1, __ATOMIC_SEQ_CST);
    while (__atomic_exchange_n(&m->locked, 1, __ATOMIC_SEQ_CST)) {
        rk_thread_yield();
    }
    __atomic_sub_fetch(&m->waiters, 1, __ATOMIC_SEQ_CST);
    return 1;
}

void mp_thread_mutex_unlock(mp_thread_mutex_t *m) {
    __atomic_store_n(&m->locked, 0, __ATOMIC_SEQ_CST);
    if (m->waiters) {
        rk_thread_yield();                  // hand over instead of re-grabbing
    }
}
