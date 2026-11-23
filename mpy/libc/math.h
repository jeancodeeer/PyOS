// Minimal <math.h> for the freestanding kernel build. It shadows the host
// header so MicroPython's bundled libm (lib/libm_dbl) provides every function.
#ifndef PYKERNEL_MATH_H
#define PYKERNEL_MATH_H

typedef float float_t;
typedef double double_t;

#define NAN         __builtin_nan("")
#define INFINITY    __builtin_inf()
#define HUGE_VAL    __builtin_huge_val()
#define HUGE_VALF   __builtin_huge_valf()

#define FP_NAN       0
#define FP_INFINITE  1
#define FP_ZERO      2
#define FP_SUBNORMAL 3
#define FP_NORMAL    4

#define fpclassify(x) __builtin_fpclassify(FP_NAN, FP_INFINITE, FP_NORMAL, FP_SUBNORMAL, FP_ZERO, x)
#define isnan(x)      __builtin_isnan(x)
#define isinf(x)      __builtin_isinf(x)
#define isfinite(x)   __builtin_isfinite(x)
#define isnormal(x)   __builtin_isnormal(x)
#define signbit(x)    __builtin_signbit(x)

#define M_E   2.7182818284590452354
#define M_PI  3.14159265358979323846

double acos(double);
double acosh(double);
double asin(double);
double asinh(double);
double atan(double);
double atan2(double, double);
double atanh(double);
double ceil(double);
double copysign(double, double);
double cos(double);
double cosh(double);
double erf(double);
double erfc(double);
double exp(double);
double expm1(double);
double floor(double);
double fmod(double, double);
double frexp(double, int *);
double ldexp(double, int);
double lgamma(double);
double log(double);
double log10(double);
double log1p(double);
double modf(double, double *);
double nearbyint(double);
double pow(double, double);
double rint(double);
double round(double);
double scalbn(double, int);
double sin(double);
double sinh(double);
double sqrt(double);
double tan(double);
double tanh(double);
double tgamma(double);
double trunc(double);

#define nan(tag) __builtin_nan(tag)

static inline double fabs(double x) {
    return __builtin_fabs(x);
}
static inline double log2(double x) {
    return log(x) * 1.4426950408889634074;
}

#endif
