// MicroPython configuration for PyKernel (bare-metal x86_64).
#include <stdint.h>
#include <stddef.h>
#include <alloca.h>

#define MICROPY_CONFIG_ROM_LEVEL            (MICROPY_CONFIG_ROM_LEVEL_EXTRA_FEATURES)

// Core
#define MICROPY_ENABLE_COMPILER             (1)
#define MICROPY_ENABLE_GC                   (1)
#define MICROPY_GC_SPLIT_HEAP               (1)   // Python can add RAM to the heap
#define MICROPY_GC_SPLIT_HEAP_AUTO          (1)   // ...and the heap grows by itself from a reserve
void *mpk_heap_alloc(size_t size);
void mpk_heap_free(void *ptr);
#define MP_PLAT_ALLOC_HEAP(size)            mpk_heap_alloc(size)
#define MP_PLAT_FREE_HEAP(ptr)              mpk_heap_free(ptr)
#define MICROPY_STACK_CHECK                 (1)
#define MICROPY_HELPER_REPL                 (1)
#define MICROPY_REPL_AUTO_INDENT            (1)
#define MICROPY_READLINE_HISTORY_SIZE       (100) // saved to /disk/.history by kernel.history
#define MICROPY_ENABLE_SOURCE_LINE          (1)
#define MICROPY_ERROR_REPORTING             (MICROPY_ERROR_REPORTING_DETAILED)
#define MICROPY_LONGINT_IMPL                (MICROPY_LONGINT_IMPL_MPZ)
#define MICROPY_FLOAT_IMPL                  (MICROPY_FLOAT_IMPL_DOUBLE)
#define MICROPY_USE_INTERNAL_ERRNO          (1)
#define MICROPY_EMIT_X64                    (1)   // @micropython.native / viper

// Interrupt handlers written in Python run on the VM scheduler.
#define MICROPY_ENABLE_SCHEDULER            (1)
#define MICROPY_SCHEDULER_DEPTH             (32)
#define MICROPY_KBD_EXCEPTION               (1)

// Preemptive threads (`_thread`), scheduled by rust/sched.rs.
#define MICROPY_PY_THREAD                   (1)
#define MICROPY_PY_THREAD_GIL               (1)
// Hand the GIL over even while scheduled callbacks are held back
// (thread_mask, or a callback that blocks). Stock MicroPython keeps it then,
// which lets a thread that never blocks starve the rest for good.
// Needs mpy/patches/vm-gil-always-bounce.patch (applied by tools/build.py).
#define MICROPY_PY_THREAD_GIL_ALWAYS_BOUNCE (1)

// Filesystems are Python objects mounted through the VFS layer.
#define MICROPY_VFS                         (1)
#define MICROPY_READER_VFS                  (1)
#define MICROPY_FATFS_ENABLE_LFN            (1)
#define MICROPY_FATFS_LFN_CODE_PAGE         437
#define MICROPY_FATFS_RPATH                 (2)
#define MICROPY_FATFS_NORTC                 (1)

// Things that are implemented in Python instead (see pyfs/lib).
#define MICROPY_PY_TIME                     (0)
#define MICROPY_PY_SELECT                   (0)
#define MICROPY_PY_ASYNCIO                  (0)
#define MICROPY_PY_PLATFORM                 (0)
#define MICROPY_PY_MACHINE                  (0)

#define MICROPY_PY_SYS_PLATFORM             "pykernel"
#define MICROPY_HW_BOARD_NAME               "PyKernel"
#define MICROPY_HW_MCU_NAME                 "x86_64"

typedef intptr_t mp_int_t;
typedef uintptr_t mp_uint_t;
typedef long mp_off_t;

uint64_t rk_irq_save(void);
void rk_irq_restore(uint64_t flags);
#define MICROPY_BEGIN_ATOMIC_SECTION()      rk_irq_save()
#define MICROPY_END_ATOMIC_SECTION(state)   rk_irq_restore(state)

#define MP_STATE_PORT MP_STATE_VM
