//! PyKernel: the Rust layer.
//!
//! Brings the CPU up, picks a heap, starts the MicroPython VM, hands control
//! to `/init.py` from the boot archive and then to the interactive console.
//! Everything that can be Python is Python; see `pyfs/`.

#![no_std]
#![no_main]

#[cfg(target_arch = "x86_64")]
mod boot;
#[cfg(target_arch = "x86_64")]
mod cpu;
#[cfg(target_arch = "x86_64")]
mod interrupts;
#[cfg(target_arch = "aarch64")]
#[path = "arm64/boot.rs"]
mod boot;
#[cfg(target_arch = "aarch64")]
#[path = "arm64/cpu.rs"]
mod cpu;
#[cfg(target_arch = "aarch64")]
#[path = "arm64/interrupts.rs"]
mod interrupts;
mod aes;
mod fast;
mod gfx;
mod py;
mod sched;
mod serial;

use core::sync::atomic::{AtomicU64, AtomicUsize, Ordering::Relaxed};

extern "C" {
    static __load_start: u8;
    static __kernel_end: u8;
    static boot_stack: u8;
    static boot_stack_top: u8;

    fn mp_init();
    fn mp_deinit();
    fn gc_init(start: *mut u8, end: *mut u8);
    fn mpk_cstack_init(top: *const u8, size: usize);
    fn mpk_init();
    fn mpk_exec(name: *const u8, src: *const u8, len: usize) -> i32;
    fn mpk_repl();
}

// ---- boot information, readable from Python via _kernel.info() ----

const INFO_LEN: usize = 32;
static INFO: [AtomicU64; INFO_LEN] = [const { AtomicU64::new(0) }; INFO_LEN];

/// The indexes of _kernel.info() (names in mpy/modkernel.c, same order).
#[allow(non_snake_case, dead_code)]
pub mod I {
    pub const KSTART: usize = 0;
    pub const KEND: usize = 1;
    pub const HEAP_START: usize = 2;
    pub const HEAP_END: usize = 3;
    pub const MBI: usize = 4;
    pub const INITRD_START: usize = 5;
    pub const INITRD_END: usize = 6;
    pub const STACK_BASE: usize = 7;
    pub const STACK_TOP: usize = 8;
    pub const IDT: usize = 9;
    pub const BOOTS: usize = 10;
    pub const POOL_START: usize = 11;
    pub const POOL_END: usize = 12;
    // ARM64 (0 on PCs, except ARCH = 0)
    pub const ARCH: usize = 13;          // 0 x86_64, 1 aarch64
    pub const FB_ADDR: usize = 14;
    pub const FB_WIDTH: usize = 15;
    pub const FB_HEIGHT: usize = 16;
    pub const FB_PITCH: usize = 17;
    pub const FB_FORMAT: usize = 18;
    pub const RSDP: usize = 19;
    pub const EPOCH: usize = 20;
    pub const ECAM: usize = 21;
    pub const PIO: usize = 22;
    pub const PSCI: usize = 23;
    pub const TIMER_HZ: usize = 24;
    pub const MMAP: usize = 25;
    pub const MMAP_SIZE: usize = 26;
    pub const MMAP_DESC: usize = 27;
    pub const TIMER_IRQ: usize = 28;
}
use I::{BOOTS as I_BOOTS, HEAP_END as I_HEAP_END, HEAP_START as I_HEAP_START, INITRD_END as I_INITRD_END,
        INITRD_START as I_INITRD_START, POOL_END as I_POOL_END, POOL_START as I_POOL_START};
#[cfg(target_arch = "x86_64")]
use I::{IDT as I_IDT, KEND as I_KEND, KSTART as I_KSTART, MBI as I_MBI, STACK_BASE as I_STACK_BASE,
        STACK_TOP as I_STACK_TOP};

pub fn info_set(i: usize, v: u64) {
    INFO[i].store(v, Relaxed);
}

#[no_mangle]
pub extern "C" fn rk_info(i: u32) -> u64 {
    INFO.get(i as usize).map_or(0, |v| v.load(Relaxed))
}

// ---- console input queue: filled by Python drivers, drained by the REPL ----

const QLEN: usize = 4096;
static mut QUEUE: [u8; QLEN] = [0; QLEN];
static QHEAD: AtomicUsize = AtomicUsize::new(0);
static QTAIL: AtomicUsize = AtomicUsize::new(0);

#[no_mangle]
pub extern "C" fn rk_stdin_push(c: u8) {
    let h = QHEAD.load(Relaxed);
    let next = (h + 1) % QLEN;
    if next != QTAIL.load(Relaxed) {
        unsafe { (*core::ptr::addr_of_mut!(QUEUE))[h] = c };
        QHEAD.store(next, Relaxed);
    }
}
#[no_mangle]
pub extern "C" fn rk_stdin_pop() -> i32 {
    let t = QTAIL.load(Relaxed);
    if t == QHEAD.load(Relaxed) {
        return -1;
    }
    let c = unsafe { (*core::ptr::addr_of!(QUEUE))[t] };
    QTAIL.store((t + 1) % QLEN, Relaxed);
    c as i32
}
#[no_mangle]
pub extern "C" fn rk_stdin_empty() -> bool {
    QTAIL.load(Relaxed) == QHEAD.load(Relaxed)
}

// ---- multiboot ----

#[cfg(target_arch = "x86_64")]
unsafe fn rd32(a: u64) -> u32 {
    core::ptr::read_unaligned(a as *const u32)
}
#[cfg(target_arch = "x86_64")]
unsafe fn rd64(a: u64) -> u64 {
    core::ptr::read_unaligned(a as *const u64)
}

#[cfg(target_arch = "x86_64")]
const MAPPED: u64 = 64 << 30;              // identity-mapped by boot.rs
const HEAP_FIRST: u64 = 48 << 20;          // the Python heap to start with...
const KEEP_FREE: u64 = 192 << 20;          // ...and RAM always left for drivers, DMA and programs

/// Record the boot archive (module 0) and choose the Python heap: a slice of
/// the largest usable RAM region above the kernel image. The rest of RAM is
/// left for Python's own memory manager, which can grow the heap later.
#[cfg(target_arch = "x86_64")]
unsafe fn scan_multiboot(magic: u32, mbi: u64) {
    let mut floor = core::ptr::addr_of!(__kernel_end) as u64;
    if magic != 0x2BADB002 {
        klog!("boot: not multiboot (magic {:#x}); assuming 64 MiB of RAM", magic);
        set_heap(floor, 64 << 20);
        return;
    }
    INFO[I_MBI].store(mbi, Relaxed);
    let flags = rd32(mbi);
    if flags & (1 << 3) != 0 && rd32(mbi + 20) > 0 {
        let mods = rd32(mbi + 24) as u64;
        INFO[I_INITRD_START].store(rd32(mods) as u64, Relaxed);
        INFO[I_INITRD_END].store(rd32(mods + 4) as u64, Relaxed);
        for i in 0..rd32(mbi + 20) as u64 {
            floor = floor.max(rd32(mods + i * 16 + 4) as u64);
        }
    }
    // The largest usable region gets the Python heap; the largest one left
    // (or the rest of the same one) becomes the heap's reserve, which
    // MicroPython takes more heap from by itself when it runs short
    // (mpy/modkernel.c, MICROPY_GC_SPLIT_HEAP_AUTO). The rest of RAM is for
    // kernel/mm.py: drivers, DMA buffers and Windows programs.
    let mut regions: [(u64, u64); 32] = [(0, 0); 32];
    let mut n = 0;
    let mut total = 0u64;
    if flags & (1 << 6) != 0 {
        let mut p = rd32(mbi + 48) as u64;
        let end = p + rd32(mbi + 44) as u64;
        while p < end && n < 32 {
            let size = rd32(p) as u64;
            if rd32(p + 20) == 1 {
                let s = rd64(p + 4).max(floor);
                let e = (rd64(p + 4) + rd64(p + 12)).min(MAPPED);
                if e > s {
                    regions[n] = (s, e);
                    n += 1;
                    total += e - s;
                }
            }
            p += size + 4;
        }
    } else if flags & 1 != 0 {
        regions[0] = (floor, (1 << 20) + ((rd32(mbi + 8) as u64) << 10));
        n = 1;
        total = regions[0].1 - regions[0].0;
    }
    if n == 0 {
        klog!("boot: no usable memory map; assuming 64 MiB of RAM");
        set_heap(floor, 64 << 20);
        return;
    }
    plan_memory(&mut regions, n, total);
}

/// The Python heap in the largest region below 4 GiB, and its reserve (see above).
pub fn plan_memory(regions: &mut [(u64, u64); 32], n: usize, total: u64) {
    // the heap: in the largest region below 4 GiB (where most RAM of small machines is)
    let mut h = 0;
    for i in 0..n {
        let (s, e) = regions[i];
        let (hs, he) = regions[h];
        if s < (1 << 32) && (e - s > he - hs || hs >= (1 << 32)) {
            h = i;
        }
    }
    set_heap(regions[h].0, regions[h].1);
    let heap_end = INFO[I_HEAP_END].load(Relaxed);
    regions[h].0 = heap_end;
    // the reserve: half of the RAM, from the largest region (above 4 GiB if there is one)
    let mut r = 0;
    for i in 0..n {
        if regions[i].1 - regions[i].0 > regions[r].1 - regions[r].0 {
            r = i;
        }
    }
    let (rs, re) = regions[r];
    let room = if re - rs > KEEP_FREE && rs < (1 << 32) { re - rs - KEEP_FREE } else { re - rs };
    let want = (total / 2).min(room) & !0xFFFFF;
    if want >= (16 << 20) {
        let start = (re - want) & !0xFFF;               // its top end: low memory stays for DMA
        INFO[I_POOL_START].store(start, Relaxed);
        INFO[I_POOL_END].store(re & !0xFFF, Relaxed);
    }
}

fn set_heap(region_start: u64, region_end: u64) {
    let start = (region_start + 0xFFF) & !0xFFF;
    let len = ((region_end - start) / 4).min(HEAP_FIRST) & !0xFFF;
    INFO[I_HEAP_START].store(start, Relaxed);
    INFO[I_HEAP_END].store(start + len, Relaxed);
}

/// Locate `init.py` in the boot archive ("PYFS", u32 count, then entries of
/// u16 name length, u32 data length, name, data).
unsafe fn find_init() -> Option<(*const u8, usize)> {
    let rd32 = |a: u64| core::ptr::read_unaligned(a as *const u32);
    let (start, end) = (INFO[I_INITRD_START].load(Relaxed), INFO[I_INITRD_END].load(Relaxed));
    if end < start + 8 || rd32(start) != u32::from_le_bytes(*b"PYFS") {
        return None;
    }
    let mut p = start + 8;
    for _ in 0..rd32(start + 4) {
        if p + 6 > end {
            break;
        }
        let nlen = core::ptr::read_unaligned(p as *const u16) as u64;
        let dlen = rd32(p + 2) as u64;
        let name = core::slice::from_raw_parts((p + 6) as *const u8, nlen as usize);
        let data = p + 6 + nlen;
        if data + dlen > end {
            break;
        }
        if name == b"init.py" {
            return Some((data as *const u8, dlen as usize));
        }
        p = data + dlen;
    }
    None
}

/// One life of the Python world: fresh VM, run init.py, serve the console
/// until it asks for a soft reboot (Ctrl-D).
unsafe fn python_session() {
    let stack_top = core::ptr::addr_of!(boot_stack_top);
    let stack_len = stack_top as usize - core::ptr::addr_of!(boot_stack) as usize;
    sched::reset(stack_top as u64);
    mpk_cstack_init(stack_top, stack_len - 0x8000);
    gc_init(INFO[I_HEAP_START].load(Relaxed) as *mut u8, INFO[I_HEAP_END].load(Relaxed) as *mut u8);
    mp_init();
    mpk_init();
    fast::register();                    // Python modules written in Rust
    aes::register();
    gfx::register();
    interrupts::IN_VM.store(true, Relaxed);
    INFO[I_BOOTS].fetch_add(1, Relaxed);

    match find_init() {
        Some((src, len)) => {
            mpk_exec(b"init.py\0".as_ptr(), src, len);
        }
        None => klog!("boot: no init.py in the boot archive; bare console only"),
    }
    mpk_repl();

    cpu::rk_cli();
    sched::reset(stack_top as u64);      // background threads die with the VM
    interrupts::reset();
    interrupts::IN_VM.store(false, Relaxed);
    while rk_stdin_pop() >= 0 {}
    mp_deinit();
}

/// The Python world, forever (each soft reboot starts a new one).
pub unsafe fn run() -> ! {
    loop {
        python_session();
        klog!("\nPyKernel: soft reboot");
    }
}

#[cfg(target_arch = "x86_64")]
#[no_mangle]
pub unsafe extern "C" fn kmain(magic: u32, mbi: u32) -> ! {
    serial::init();
    klog!("\nPyKernel: rust layer up");
    interrupts::init();
    INFO[I_KSTART].store(core::ptr::addr_of!(__load_start) as u64, Relaxed);
    INFO[I_KEND].store(core::ptr::addr_of!(__kernel_end) as u64, Relaxed);
    INFO[I_STACK_BASE].store(core::ptr::addr_of!(boot_stack) as u64, Relaxed);
    INFO[I_STACK_TOP].store(core::ptr::addr_of!(boot_stack_top) as u64, Relaxed);
    INFO[I_IDT].store(interrupts::idt_addr(), Relaxed);
    scan_multiboot(magic, mbi as u64);
    klog!(
        "PyKernel: python heap {:#x}..{:#x}, starting VM",
        INFO[I_HEAP_START].load(Relaxed),
        INFO[I_HEAP_END].load(Relaxed)
    );
    run()
}

/// Called by the C glue when the VM hits an unrecoverable state.
#[no_mangle]
pub extern "C" fn rk_fatal(code: u64) -> ! {
    klog!("\n*** PyKernel fatal: VM error {:#x} -- halted", code);
    cpu::halt_forever()
}

#[panic_handler]
fn panic(info: &core::panic::PanicInfo) -> ! {
    klog!("\n*** PyKernel rust panic: {}", info);
    cpu::halt_forever()
}
