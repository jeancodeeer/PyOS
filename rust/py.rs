//! Talking to the MicroPython VM from Rust: the few C functions and types of
//! MicroPython that the kernel's Python modules need, and helpers to build
//! builtin functions and modules at run time (no C glue).
//!
//!   static F: FunVar = Fun::var(2, 3, my_fn);   // def my_fn(a, b, c=...)
//!   let m = py::module("_name");                // import _name works from here on
//!   py::set(m, "my_fn", py::fun(&F));
#![allow(dead_code)]

use core::ffi::c_void;

pub type Obj = usize;
pub type Qstr = usize;

#[repr(C)]
pub struct BufInfo {
    pub buf: *mut u8,
    pub len: usize,
    pub typecode: i32,
}

extern "C" {
    static mp_type_fun_builtin_var: u8;
    static mp_type_fun_builtin_0: u8;
    static mp_type_fun_builtin_1: u8;
    static mp_type_fun_builtin_2: u8;
    static mp_type_fun_builtin_3: u8;
    static mp_type_int: u8;

    fn qstr_from_strn(s: *const u8, len: usize) -> Qstr;
    fn mp_obj_new_module(name: Qstr) -> Obj;
    fn mp_store_attr(base: Obj, attr: Qstr, val: Obj);
    fn mp_get_buffer(o: Obj, info: *mut BufInfo, flags: usize) -> bool;
    fn mp_obj_get_int_truncated(o: Obj) -> isize;
    fn mp_obj_get_type(o: Obj) -> *const u8;
    fn mp_obj_new_int_from_ll(v: i64) -> Obj;
    fn mp_obj_new_int_from_ull(v: u64) -> Obj;
    fn mp_obj_new_bytes(data: *const u8, len: usize) -> Obj;
    fn mp_obj_is_true(o: Obj) -> bool;
    fn vstr_init_len(v: *mut Vstr, len: usize);
    fn vstr_clear(v: *mut Vstr);
    fn mp_obj_new_bytes_from_vstr(v: *mut Vstr) -> Obj;
    fn mp_raise_ValueError(msg: *const u8) -> !;
    fn mp_raise_TypeError(msg: *const u8) -> !;
}

pub type VarFn = unsafe extern "C" fn(usize, *const Obj) -> Obj;
pub type Fn0 = unsafe extern "C" fn() -> Obj;
pub type Fn1 = unsafe extern "C" fn(Obj) -> Obj;
pub type Fn2 = unsafe extern "C" fn(Obj, Obj) -> Obj;
pub type Fn3 = unsafe extern "C" fn(Obj, Obj, Obj) -> Obj;

/// A builtin function object taking any number of arguments, laid out as
/// MicroPython's mp_obj_fun_builtin_var_t.
#[repr(C)]
pub struct FunVar {
    ty: *const u8,
    sig: usize,              // a uint32_t, then padding
    fun: VarFn,
}
unsafe impl Sync for FunVar {}

/// A builtin function object with a fixed number (0-3) of arguments
/// (mp_obj_fun_builtin_fixed_t).
#[repr(C)]
pub struct FunFixed<F> {
    ty: *const u8,
    fun: F,
}
unsafe impl<F> Sync for FunFixed<F> {}

const fn make_sig(min: u32, max: u32) -> usize {
    ((min << 17) | (max << 1)) as usize
}

pub struct Fun;
impl Fun {
    /// fn(n_args, args) taking between min and max arguments.
    pub const fn var(min: u32, max: u32, f: VarFn) -> FunVar {
        FunVar { ty: core::ptr::addr_of!(mp_type_fun_builtin_var), sig: make_sig(min, max), fun: f }
    }
    pub const fn f0(f: Fn0) -> FunFixed<Fn0> {
        FunFixed { ty: core::ptr::addr_of!(mp_type_fun_builtin_0), fun: f }
    }
    pub const fn f1(f: Fn1) -> FunFixed<Fn1> {
        FunFixed { ty: core::ptr::addr_of!(mp_type_fun_builtin_1), fun: f }
    }
    pub const fn f2(f: Fn2) -> FunFixed<Fn2> {
        FunFixed { ty: core::ptr::addr_of!(mp_type_fun_builtin_2), fun: f }
    }
    pub const fn f3(f: Fn3) -> FunFixed<Fn3> {
        FunFixed { ty: core::ptr::addr_of!(mp_type_fun_builtin_3), fun: f }
    }
}

/// The Python object of a static builtin function.
pub fn fun<T>(f: &'static T) -> Obj {
    f as *const T as Obj
}

pub fn qstr(name: &str) -> Qstr {
    unsafe { qstr_from_strn(name.as_ptr(), name.len()) }
}

/// A new module, importable by `name` from now on.
pub fn module(name: &str) -> Obj {
    unsafe { mp_obj_new_module(qstr(name)) }
}

pub fn set(obj: Obj, name: &str, value: Obj) {
    unsafe { mp_store_attr(obj, qstr(name), value) }
}

/// A new module `name` holding `items` (name, object).
pub fn define(name: &str, items: &[(&str, Obj)]) -> Obj {
    let m = module(name);
    for (n, o) in items {
        set(m, n, *o);
    }
    m
}

// None, False and True are immediate objects (object representation A):
// MP_OBJ_NEW_IMMEDIATE_OBJ(n) = n << 3 | 6
pub const NONE: Obj = 6;
pub const FALSE: Obj = (1 << 3) | 6;
pub const TRUE: Obj = (3 << 3) | 6;

pub fn none() -> Obj {
    NONE
}
pub fn boolean(b: bool) -> Obj {
    if b { TRUE } else { FALSE }
}
pub fn truthy(o: Obj) -> bool {
    unsafe { mp_obj_is_true(o) }
}

fn is_int(o: Obj) -> bool {
    o & 1 == 1 || unsafe { mp_obj_get_type(o) == core::ptr::addr_of!(mp_type_int) }
}

/// An integer argument (wrapping, as viper does).
pub fn int(o: Obj) -> isize {
    unsafe { mp_obj_get_int_truncated(o) }
}

pub fn new_int(v: i64) -> Obj {
    if (-(1i64 << 61)..(1i64 << 61)).contains(&v) {
        ((v << 1) | 1) as Obj                 // a small int, in the object word itself
    } else {
        unsafe { mp_obj_new_int_from_ll(v) }
    }
}
pub fn new_uint(v: u64) -> Obj {
    if v < (1u64 << 61) { new_int(v as i64) } else { unsafe { mp_obj_new_int_from_ull(v) } }
}

/// MicroPython's vstr_t: a growable buffer on the Python heap.
#[repr(C)]
pub struct Vstr {
    alloc: usize,
    len: usize,
    buf: *mut u8,
    fixed_buf: bool,
}

/// A bytes object of `len` bytes, filled in by `fill` (no copy).
pub fn new_bytes_with(len: usize, fill: impl FnOnce(&mut [u8])) -> Obj {
    unsafe {
        let mut v = Vstr { alloc: 0, len: 0, buf: core::ptr::null_mut(), fixed_buf: false };
        vstr_init_len(&mut v, len);
        fill(core::slice::from_raw_parts_mut(v.buf, len));
        mp_obj_new_bytes_from_vstr(&mut v)
    }
}

/// Like new_bytes_with, but `fill` may decline (returns false): None then.
pub fn new_bytes_or_none(len: usize, fill: impl FnOnce(&mut [u8]) -> bool) -> Obj {
    unsafe {
        let mut v = Vstr { alloc: 0, len: 0, buf: core::ptr::null_mut(), fixed_buf: false };
        vstr_init_len(&mut v, len);
        if !fill(core::slice::from_raw_parts_mut(v.buf, len)) {
            vstr_clear(&mut v);
            return NONE;
        }
        mp_obj_new_bytes_from_vstr(&mut v)
    }
}

/// The bytes of a buffer object, as a slice.
pub fn bytes<'a>(o: Obj) -> &'a [u8] {
    let (p, n) = buffer(o);
    if n == 0 {
        return &[];
    }
    unsafe { core::slice::from_raw_parts(p, n) }
}

pub fn new_bytes(data: &[u8]) -> Obj {
    unsafe { mp_obj_new_bytes(data.as_ptr(), data.len()) }
}

/// A "pointer" argument: an address, or the memory of a buffer object
/// (bytes, bytearray, array, memoryview).
pub fn ptr<T>(o: Obj) -> *mut T {
    if is_int(o) {
        return int(o) as usize as *mut T;
    }
    buffer(o).0 as *mut T
}

/// (address, length in bytes) of a buffer object.
pub fn buffer(o: Obj) -> (*mut u8, usize) {
    let mut info = BufInfo { buf: core::ptr::null_mut(), len: 0, typecode: 0 };
    unsafe { mp_get_buffer(o, &mut info, 1 | 4) };
    (info.buf, info.len)
}

pub fn value_error(msg: &'static [u8]) -> ! {
    unsafe { mp_raise_ValueError(msg.as_ptr()) }
}
pub fn type_error(msg: &'static [u8]) -> ! {
    unsafe { mp_raise_TypeError(msg.as_ptr()) }
}

pub fn args<'a>(n: usize, a: *const Obj) -> &'a [Obj] {
    unsafe { core::slice::from_raw_parts(a, n) }
}

#[allow(unused)]
pub fn as_void(o: Obj) -> *mut c_void {
    o as *mut c_void
}
