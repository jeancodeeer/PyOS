#include <stddef.h>
#include <stdint.h>
#include "shared/runtime/interrupt_char.h"

// Timekeeping is Python's job (/lib/time.py); the VM itself needs none.
static inline mp_uint_t mp_hal_ticks_ms(void) {
    return 0;
}
