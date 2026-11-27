// The bits of a C library that QuickJS needs and the kernel's small one does
// not have: a few maths functions, the clock, 128-bit division, and empty
// stand-ins for things that need an operating system (threads, abort).
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <time.h>
#include <sys/time.h>
#include "py/mphal.h"
#include "py/runtime.h"

// ---- maths ----

double cbrt(double x) {
    if (x == 0 || x != x || x == INFINITY || x == -INFINITY) {
        return x;
    }
    double y = x < 0 ? -pow(-x, 1.0 / 3.0) : pow(x, 1.0 / 3.0);
    y = y - (y * y * y - x) / (3 * y * y);       // one Newton step: exact cubes come out exact
    return y;
}

double hypot(double x, double y) {
    x = fabs(x);
    y = fabs(y);
    if (x == INFINITY || y == INFINITY) {
        return INFINITY;
    }
    double big = x > y ? x : y, small = x > y ? y : x;
    if (big == 0) {
        return 0;
    }
    double r = small / big;
    return big * sqrt(1 + r * r);
}

long lrint(double x) {
    return (long)rint(x);
}

double fmin(double a, double b) {
    if (a != a) return b;
    if (b != b) return a;
    return a < b ? a : b;
}

double fmax(double a, double b) {
    if (a != a) return b;
    if (b != b) return a;
    return a > b ? a : b;
}

char *strrchr(const char *s, int c) {
    const char *last = NULL;
    do {
        if (*s == (char)c) {
            last = s;
        }
    } while (*s++);
    return (char *)last;
}

// ---- 128-bit division (QuickJS's number printing uses it) ----

typedef unsigned __int128 u128;

u128 __udivmodti4(u128 n, u128 d, u128 *rem) {
    u128 q = 0, r = 0;
    for (int i = 127; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1);
        if (r >= d) {
            r -= d;
            q |= (u128)1 << i;
        }
    }
    if (rem) {
        *rem = r;
    }
    return q;
}

u128 __udivti3(u128 n, u128 d) {
    return __udivmodti4(n, d, NULL);
}

u128 __umodti3(u128 n, u128 d) {
    u128 r;
    __udivmodti4(n, d, &r);
    return r;
}

// ---- the clock: Python tells the wall time once (_js.set_clock) and how fast the
// CPU's time-stamp counter runs (kernel.timer.tsc_per_ms); the counter does the rest ----

static int64_t wall_base_ms;      // milliseconds since 1970 when tsc_base was read
static uint64_t tsc_base, tsc_per_ms = 1000000;
static int tz_minutes;

uint64_t rk_rdtsc(void);          // the CPU's counter (x86: TSC; ARM64: the generic timer)

static inline uint64_t rdtsc(void) {
    return rk_rdtsc();
}

void js_shim_set_clock(int64_t epoch_ms, int tz, uint64_t per_ms) {
    wall_base_ms = epoch_ms;
    tsc_base = rdtsc();
    tz_minutes = tz;
    if (per_ms) {
        tsc_per_ms = per_ms;
    }
}

// milliseconds since the clock was set (or since the counter started)
uint64_t js_shim_ms(void) {
    return (rdtsc() - tsc_base) / tsc_per_ms;
}

static int64_t now_ms(void) {
    return wall_base_ms + (int64_t)js_shim_ms();
}

int gettimeofday(struct timeval *tv, void *tz) {
    int64_t ms = now_ms();
    tv->tv_sec = ms / 1000;
    tv->tv_usec = (ms % 1000) * 1000;
    return 0;
}

int clock_gettime(clockid_t id, struct timespec *ts) {
    int64_t ms = id == CLOCK_REALTIME ? now_ms() : (int64_t)js_shim_ms();
    ts->tv_sec = ms / 1000;
    ts->tv_nsec = (ms % 1000) * 1000000;
    return 0;
}

// local time = UTC + the time zone from Settings (no summer time rules here)
struct tm *localtime_r(const time_t *t, struct tm *out) {
    int64_t s = (int64_t)*t + tz_minutes * 60;
    int64_t days = s / 86400, rem = s % 86400;
    if (rem < 0) {
        rem += 86400;
        days -= 1;
    }
    out->tm_hour = rem / 3600;
    out->tm_min = rem % 3600 / 60;
    out->tm_sec = rem % 60;
    out->tm_wday = (int)((days % 7 + 11) % 7);        // 1 Jan 1970 was a Thursday
    // days -> year, month, day (Howard Hinnant's civil_from_days)
    int64_t z = days + 719468;
    int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    unsigned doe = (unsigned)(z - era * 146097);
    unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t y = (int64_t)yoe + era * 400;
    unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    unsigned mp = (5 * doy + 2) / 153;
    unsigned d = doy - (153 * mp + 2) / 5 + 1;
    unsigned m = mp < 10 ? mp + 3 : mp - 9;
    y += m <= 2;
    out->tm_year = (int)(y - 1900);
    out->tm_mon = (int)m - 1;
    out->tm_mday = (int)d;
    out->tm_yday = 0;
    out->tm_isdst = 0;
    out->tm_gmtoff = tz_minutes * 60;
    out->tm_zone = "";
    return out;
}

// ---- no operating system here ----

// QuickJS calls abort() only when something inside it is badly wrong: stop the
// script with a Python exception instead of stopping the whole computer.
void abort(void) {
    mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("JavaScript engine: internal error"));
    for (;;) {
    }
}
