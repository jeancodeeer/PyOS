// Thread port for PyKernel: mutexes are spin-and-yield locks on top of the
// Rust scheduler (rust/sched.rs).
typedef struct _mp_thread_mutex_t {
    volatile int locked;
    volatile int waiters;
} mp_thread_mutex_t;
