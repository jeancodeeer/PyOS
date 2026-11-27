// _js: JavaScript, with QuickJS (Fabrice Bellard's engine, ES2023) inside the
// kernel. The browser builds its DOM in JavaScript on top of this.
//
//   ctx = _js.Context(callback)       callback(name, json_text) -> json_text: what JS's __py() calls
//   ctx.eval(code, name="<script>", timeout_ms=3000, mem_extra=0) -> the result (None, bool, int, float, str;
//                                                     objects come back as JSON text)
//   ctx.run_jobs()                    run waiting promise reactions; returns how many ran
//   ctx.memory()                      bytes the engine uses
//   ctx.close()
//   _js.set_clock(epoch_ms, tz_minutes, tsc_per_ms)   the wall clock for Date
//
// A script that throws raises _js.Error with JavaScript's message and stack.
// A script that runs past its time is stopped (an uncatchable "interrupted").
// The engine's memory comes from the media arena (media.init() first).
#include <string.h>
#include "py/runtime.h"
#include "py/obj.h"
#include "py/objstr.h"
#include "py/mphal.h"
#include "py/mpthread.h"
#include "js/quickjs/quickjs.h"

void js_shim_set_clock(int64_t epoch_ms, int tz, uint64_t tsc_per_ms);
uint64_t js_shim_ms(void);
#define NOW_MS() ((uint32_t)js_shim_ms())
void *malloc(size_t n);
void free(void *p);
void *realloc(void *p, size_t n);
size_t malloc_usable_size(void *p);

MP_DEFINE_EXCEPTION(JSError, Exception)
JSValue JS_PyKernelBacktrace(JSContext *ctx);

typedef struct {
    mp_obj_base_t base;
    JSRuntime *rt;
    JSContext *ctx;
    mp_obj_t callback;
    uint32_t deadline;          // ticks_ms when the running script must stop (0: no limit)
    int interrupted;            // 1: ran too long, 2: used too much memory
    JSMallocState *ms;          // the engine's memory count
    size_t mem_cap;             // the running script may not take the count past this (0: no cap)
} js_obj_t;

static const mp_obj_type_t js_context_type;

// ---- memory: the media arena (counted, so JS_SetMemoryLimit works) ----

#define OVERHEAD 16

static void *js_m_malloc(JSMallocState *s, size_t size) {
    if (s->opaque) {
        ((js_obj_t *)s->opaque)->ms = s;
    }
    if (s->malloc_size + size > s->malloc_limit) {
        return NULL;
    }
    void *p = malloc(size);
    if (p) {
        s->malloc_count++;
        s->malloc_size += malloc_usable_size(p) + OVERHEAD;
    }
    return p;
}

static void js_m_free(JSMallocState *s, void *ptr) {
    if (!ptr) {
        return;
    }
    s->malloc_count--;
    s->malloc_size -= malloc_usable_size(ptr) + OVERHEAD;
    free(ptr);
}

static void *js_m_realloc(JSMallocState *s, void *ptr, size_t size) {
    if (!ptr) {
        return size ? js_m_malloc(s, size) : NULL;
    }
    if (size == 0) {
        js_m_free(s, ptr);
        return NULL;
    }
    size_t old = malloc_usable_size(ptr);
    if (s->malloc_size + size - old > s->malloc_limit) {
        return NULL;
    }
    void *p = realloc(ptr, size);
    if (p) {
        s->malloc_size += malloc_usable_size(p) - old;
    }
    return p;
}

static size_t js_m_usable(const void *ptr) {
    return malloc_usable_size((void *)ptr);
}

static const JSMallocFunctions malloc_funcs = {
    js_m_malloc, js_m_free, js_m_realloc, js_m_usable,
};

// ---- stopping scripts that run too long ----

static char stop_stack[2048];       // where the last stopped script was (for finding runaway loops)

static void remember_stack(js_obj_t *self) {
    JSValue e = JS_PyKernelBacktrace(self->ctx);         // the JS call stack, right now
    JSValue st = JS_GetPropertyStr(self->ctx, e, "stack");
    const char *s = JS_ToCString(self->ctx, st);
    if (s) {
        strncpy(stop_stack, s, sizeof(stop_stack) - 1);
        stop_stack[sizeof(stop_stack) - 1] = 0;
        JS_FreeCString(self->ctx, s);
    }
    JS_FreeValue(self->ctx, st);
    JS_FreeValue(self->ctx, e);
}

static int interrupt_handler(JSRuntime *rt, void *opaque) {
    js_obj_t *self = opaque;
    if (self->deadline && (int32_t)(NOW_MS() - self->deadline) > 0) {
        self->interrupted = 1;
        return 1;
    }
    if (self->mem_cap && self->ms && self->ms->malloc_size > self->mem_cap) {
        self->interrupted = 2;                 // a runaway script: stop it before it eats the page's memory
        self->mem_cap = 0;
        remember_stack(self);
        return 1;
    }
    return 0;
}

// ---- JavaScript -> Python ----

static mp_obj_t text_of(JSContext *ctx, JSValueConst v) {
    size_t len;
    const char *s = JS_ToCStringLen(ctx, &len, v);
    if (!s) {
        return mp_obj_new_str("", 0);
    }
    mp_obj_t out = mp_obj_new_str(s, len);
    JS_FreeCString(ctx, s);
    return out;
}

// __py(name, json) -> json: the page's scripts ask the browser for things
// (fetch, the clock, layout sizes, cookies...). Python exceptions become JS errors.
static JSValue js_py_call(JSContext *ctx, JSValueConst this_val, int argc, JSValueConst *argv) {
    js_obj_t *self = JS_GetContextOpaque(ctx);
    if (!self || self->callback == mp_const_none || argc < 1) {
        return JS_UNDEFINED;
    }
    // JavaScript runs without the GIL (the desktop keeps going); Python needs it back
    MP_THREAD_GIL_ENTER();
    JSValue out = JS_UNDEFINED;
    mp_obj_t name = text_of(ctx, argv[0]);
    mp_obj_t arg = argc > 1 ? text_of(ctx, argv[1]) : mp_const_none;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_obj_t res = mp_call_function_2(self->callback, name, arg);
        nlr_pop();
        if (res != mp_const_none) {
            size_t len;
            const char *s = mp_obj_str_get_data(res, &len);
            out = JS_NewStringLen(ctx, s, len);
        }
    } else {
        mp_obj_t exc = MP_OBJ_FROM_PTR(nlr.ret_val);
        vstr_t v;
        vstr_init(&v, 64);
        mp_print_t pr;
        vstr_init_print(&v, 64, &pr);
        mp_obj_print_helper(&pr, exc, PRINT_REPR);
        out = JS_ThrowInternalError(ctx, "%s", vstr_null_terminated_str(&v));
        vstr_clear(&v);
    }
    MP_THREAD_GIL_EXIT();
    return out;
}

// ---- the context ----

static void check_open(js_obj_t *self) {
    if (!self->ctx) {
        mp_raise_ValueError(MP_ERROR_TEXT("JavaScript context is closed"));
    }
}

// Context(callback=None)
static mp_obj_t js_context_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 0, 1, false);
    js_obj_t *self = mp_obj_malloc(js_obj_t, type);
    self->callback = n_args ? args[0] : mp_const_none;
    self->rt = JS_NewRuntime2(&malloc_funcs, self);
    if (!self->rt) {
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("no memory for JavaScript (media.init() first?)"));
    }
    JS_SetMemoryLimit(self->rt, 96u << 20);
    JS_SetMaxStackSize(self->rt, 96u << 10);
    JS_SetInterruptHandler(self->rt, interrupt_handler, self);
    self->ctx = JS_NewContext(self->rt);
    if (!self->ctx) {
        JS_FreeRuntime(self->rt);
        self->rt = NULL;
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("no memory for a JavaScript context"));
    }
    JS_SetContextOpaque(self->ctx, self);
    JSValue global = JS_GetGlobalObject(self->ctx);
    JS_SetPropertyStr(self->ctx, global, "__py", JS_NewCFunction(self->ctx, js_py_call, "__py", 2));
    JS_FreeValue(self->ctx, global);
    return MP_OBJ_FROM_PTR(self);
}

// A JavaScript value as a Python one (objects as JSON text)
static mp_obj_t to_python(JSContext *ctx, JSValueConst v) {
    if (JS_IsUndefined(v) || JS_IsNull(v)) {
        return mp_const_none;
    }
    if (JS_IsBool(v)) {
        return mp_obj_new_bool(JS_ToBool(ctx, v));
    }
    if (JS_IsNumber(v)) {
        double d;
        JS_ToFloat64(ctx, &d, v);
        if (d == (double)(int64_t)d && d > -9.0e15 && d < 9.0e15) {
            return mp_obj_new_int_from_ll((long long)d);
        }
        return mp_obj_new_float(d);
    }
    if (JS_IsString(v)) {
        return text_of(ctx, v);
    }
    JSValue json = JS_JSONStringify(ctx, v, JS_UNDEFINED, JS_UNDEFINED);
    mp_obj_t out = JS_IsException(json) ? mp_const_none : to_python(ctx, json);
    JS_FreeValue(ctx, json);
    return out;
}

static void raise_js_error(js_obj_t *self) {
    JSContext *ctx = self->ctx;
    JSValue exc = JS_GetException(ctx);
    mp_obj_t msg = text_of(ctx, exc);
    if (JS_IsError(ctx, exc)) {
        JSValue stack = JS_GetPropertyStr(ctx, exc, "stack");
        if (JS_IsString(stack)) {
            vstr_t v;
            vstr_init(&v, 128);
            size_t a, b;
            const char *m = mp_obj_str_get_data(msg, &a);
            vstr_add_strn(&v, m, a);
            vstr_add_char(&v, '\n');
            mp_obj_t st = text_of(ctx, stack);
            const char *t = mp_obj_str_get_data(st, &b);
            vstr_add_strn(&v, t, b);
            msg = mp_obj_new_str_from_vstr(&v);
        }
        JS_FreeValue(ctx, stack);
    }
    JS_FreeValue(ctx, exc);
    if (self->interrupted) {
        int why = self->interrupted;
        self->interrupted = 0;
        // say why, and keep where it was (the stack) to find the loop
        vstr_t v;
        vstr_init(&v, 128);
        vstr_add_str(&v, why == 2 ? "script stopped: it used too much memory\n" : "script stopped: it ran too long\n");
        size_t n;
        const char *m = mp_obj_str_get_data(msg, &n);
        vstr_add_strn(&v, m, n);
        mp_raise_type_arg(&mp_type_JSError, mp_obj_new_str_from_vstr(&v));
    }
    mp_raise_type_arg(&mp_type_JSError, msg);
}

// eval(code, name="<script>", timeout_ms=3000)
static mp_obj_t js_eval(size_t n_args, const mp_obj_t *args) {
    js_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    check_open(self);
    size_t len;
    const char *code = mp_obj_str_get_data(args[1], &len);
    const char *name = n_args > 2 ? mp_obj_str_get_str(args[2]) : "<script>";
    mp_int_t timeout = n_args > 3 ? mp_obj_get_int(args[3]) : 3000;
    mp_int_t extra = n_args > 4 ? mp_obj_get_int(args[4]) : 0;      // how much more memory this script may take
    self->mem_cap = extra > 0 && self->ms ? self->ms->malloc_size + (size_t)extra : 0;
    // the C stack may be another thread's than last time
    JS_UpdateStackTop(self->rt);
    self->deadline = timeout > 0 ? NOW_MS() + (uint32_t)timeout : 0;
    if (!self->deadline && timeout > 0) {
        self->deadline = 1;
    }
    self->interrupted = 0;
    // The code and its name go out of Python's heap (with a 0 after, as QuickJS wants), so
    // the GIL can be let go while it runs: the desktop draws and answers meanwhile.
    char *copy = malloc(len + 1);
    size_t nlen = strlen(name);
    char *ncopy = malloc(nlen + 1);
    if (!copy || !ncopy) {
        free(copy);
        free(ncopy);
        mp_raise_msg(&mp_type_MemoryError, MP_ERROR_TEXT("no memory for the script"));
    }
    memcpy(copy, code, len);
    copy[len] = 0;
    memcpy(ncopy, name, nlen + 1);
    MP_THREAD_GIL_EXIT();
    JSValue r = JS_Eval(self->ctx, copy, len, ncopy, JS_EVAL_TYPE_GLOBAL);
    MP_THREAD_GIL_ENTER();
    free(copy);
    free(ncopy);
    self->deadline = 0;
    self->mem_cap = 0;
    if (JS_IsException(r)) {
        raise_js_error(self);
    }
    mp_obj_t out = to_python(self->ctx, r);
    JS_FreeValue(self->ctx, r);
    return out;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(js_eval_obj, 2, 5, js_eval);

// run_jobs(timeout_ms=1000, mem_extra=0) -> how many promise jobs ran
static mp_obj_t js_run_jobs(size_t n_args, const mp_obj_t *args) {
    js_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    check_open(self);
    mp_int_t timeout = n_args > 1 ? mp_obj_get_int(args[1]) : 1000;
    mp_int_t extra = n_args > 2 ? mp_obj_get_int(args[2]) : 0;
    JS_UpdateStackTop(self->rt);
    self->deadline = NOW_MS() + (uint32_t)timeout;
    self->mem_cap = extra > 0 && self->ms ? self->ms->malloc_size + (size_t)extra : 0;
    int count = 0;
    for (;;) {
        JSContext *jctx;
        MP_THREAD_GIL_EXIT();
        int r = JS_ExecutePendingJob(self->rt, &jctx);
        MP_THREAD_GIL_ENTER();
        if (r <= 0) {
            if (r < 0) {
                JSValue exc = JS_GetException(jctx);      // an unhandled error in a job: dropped
                JS_FreeValue(jctx, exc);
                if (self->interrupted) {
                    break;
                }
                continue;
            }
            break;
        }
        count++;
    }
    self->deadline = 0;
    self->mem_cap = 0;
    self->interrupted = 0;
    return mp_obj_new_int(count);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(js_run_jobs_obj, 1, 3, js_run_jobs);

static mp_obj_t js_memory(mp_obj_t self_in) {
    js_obj_t *self = MP_OBJ_TO_PTR(self_in);
    check_open(self);
    JSMemoryUsage u;
    JS_ComputeMemoryUsage(self->rt, &u);
    return mp_obj_new_int_from_ll(u.malloc_size);
}
static MP_DEFINE_CONST_FUN_OBJ_1(js_memory_obj, js_memory);

static mp_obj_t js_gc(mp_obj_t self_in) {
    js_obj_t *self = MP_OBJ_TO_PTR(self_in);
    check_open(self);
    JS_RunGC(self->rt);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(js_gc_obj, js_gc);

static mp_obj_t js_close(mp_obj_t self_in) {
    js_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->ctx) {
        JS_FreeContext(self->ctx);
        JS_FreeRuntime(self->rt);
        self->ctx = NULL;
        self->rt = NULL;
    }
    self->callback = mp_const_none;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(js_close_obj, js_close);

static const mp_rom_map_elem_t js_context_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_eval), MP_ROM_PTR(&js_eval_obj) },
    { MP_ROM_QSTR(MP_QSTR_run_jobs), MP_ROM_PTR(&js_run_jobs_obj) },
    { MP_ROM_QSTR(MP_QSTR_memory), MP_ROM_PTR(&js_memory_obj) },
    { MP_ROM_QSTR(MP_QSTR_gc), MP_ROM_PTR(&js_gc_obj) },
    { MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&js_close_obj) },
};
static MP_DEFINE_CONST_DICT(js_context_locals, js_context_locals_table);

static MP_DEFINE_CONST_OBJ_TYPE(
    js_context_type, MP_QSTR_Context, MP_TYPE_FLAG_NONE,
    make_new, js_context_make_new,
    locals_dict, &js_context_locals
    );

// set_clock(epoch_ms, tz_minutes, tsc_per_ms): the wall clock for Date, and the
// speed of the CPU's counter (for timing scripts)
static mp_obj_t js_set_clock(mp_obj_t ms, mp_obj_t tz, mp_obj_t per_ms) {
    js_shim_set_clock((int64_t)mp_obj_get_float(ms), mp_obj_get_int(tz), (uint64_t)mp_obj_get_int(per_ms));
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_3(js_set_clock_obj, js_set_clock);

// last_stop() -> where the last script stopped for memory was (its JS stack)
static mp_obj_t js_last_stop(void) {
    return mp_obj_new_str(stop_stack, strlen(stop_stack));
}
static MP_DEFINE_CONST_FUN_OBJ_0(js_last_stop_obj, js_last_stop);

static const mp_rom_map_elem_t js_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__js) },
    { MP_ROM_QSTR(MP_QSTR_Context), MP_ROM_PTR(&js_context_type) },
    { MP_ROM_QSTR(MP_QSTR_Error), MP_ROM_PTR(&mp_type_JSError) },
    { MP_ROM_QSTR(MP_QSTR_set_clock), MP_ROM_PTR(&js_set_clock_obj) },
    { MP_ROM_QSTR(MP_QSTR_last_stop), MP_ROM_PTR(&js_last_stop_obj) },
};
static MP_DEFINE_CONST_DICT(js_globals, js_globals_table);

const mp_obj_module_t mp_module_js = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&js_globals,
};

MP_REGISTER_MODULE(MP_QSTR__js, mp_module_js);
