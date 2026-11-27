//! COM1, polled. This is the kernel's always-available rescue channel:
//! boot log, panics, and console I/O until (or if ever) Python takes over.

use core::fmt;

#[cfg(target_arch = "x86_64")]
mod port {
    use crate::cpu::{inb, outb};
    const COM1: u16 = 0x3F8;

    pub fn init() {
        unsafe {
            outb(COM1 + 1, 0x00); // no interrupts (Python enables them later)
            outb(COM1 + 3, 0x80); // DLAB
            outb(COM1, 0x01); // 115200 baud
            outb(COM1 + 1, 0x00);
            outb(COM1 + 3, 0x03); // 8N1
            outb(COM1 + 2, 0xC7); // FIFO on, cleared
            outb(COM1 + 4, 0x0B); // DTR | RTS | OUT2
        }
    }

    pub fn put(b: u8) {
        unsafe {
            let mut spins = 0u32;
            while inb(COM1 + 5) & 0x20 == 0 && spins < 1_000_000 {
                spins += 1;
            }
            outb(COM1, b);
        }
    }

    pub fn rx() -> i32 {
        unsafe {
            if inb(COM1 + 5) & 1 != 0 {
                inb(COM1) as i32
            } else {
                -1
            }
        }
    }
}

/// ARM64: a PL011 UART (its address comes from ACPI's SPCR table), already
/// set up by the firmware.
#[cfg(target_arch = "aarch64")]
mod port {
    use core::ptr::{read_volatile as rd, write_volatile as wr};
    static mut BASE: u64 = 0;

    pub fn init(base: u64) {
        unsafe { BASE = base };
    }

    pub fn put(b: u8) {
        unsafe {
            if BASE == 0 {
                return;
            }
            let mut spins = 0u32;
            while rd((BASE + 0x18) as *const u32) & (1 << 5) != 0 && spins < 1_000_000 {
                spins += 1;
            }
            wr(BASE as *mut u32, b as u32);
        }
    }

    pub fn rx() -> i32 {
        unsafe {
            if BASE == 0 || rd((BASE + 0x18) as *const u32) & (1 << 4) != 0 {
                -1
            } else {
                (rd(BASE as *const u32) & 0xFF) as i32
            }
        }
    }
}

pub use port::{init, put};

pub fn write(bytes: &[u8]) {
    for &b in bytes {
        put(b);
    }
}

/// Non-blocking receive: -1 when nothing is waiting.
#[no_mangle]
pub extern "C" fn rk_serial_rx() -> i32 {
    port::rx()
}

#[no_mangle]
pub unsafe extern "C" fn rk_serial_write(p: *const u8, len: usize) {
    write(core::slice::from_raw_parts(p, len));
}

pub struct Serial;

// Everything the Rust layer logs is also kept in a small ring, so Python
// can show the boot log later (`dmesg`) even when no serial port is attached.
const KLOG_LEN: usize = 8192;
static mut KLOG: [u8; KLOG_LEN] = [0; KLOG_LEN];
static mut KLOG_POS: usize = 0; // total bytes ever logged

fn klog_byte(b: u8) {
    unsafe {
        (*core::ptr::addr_of_mut!(KLOG))[KLOG_POS % KLOG_LEN] = b;
        KLOG_POS += 1;
    }
}

/// Copy the most recent kernel log bytes into `out` (oldest first).
#[no_mangle]
pub unsafe extern "C" fn rk_klog(out: *mut u8, cap: usize) -> usize {
    let flags = crate::cpu::rk_irq_save();
    let total = KLOG_POS;
    let n = total.min(KLOG_LEN).min(cap);
    for i in 0..n {
        *out.add(i) = (*core::ptr::addr_of!(KLOG))[(total - n + i) % KLOG_LEN];
    }
    crate::cpu::rk_irq_restore(flags);
    n
}

impl fmt::Write for Serial {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        for b in s.bytes() {
            if b == b'\n' {
                put(b'\r');
            }
            put(b);
            klog_byte(b);
        }
        Ok(())
    }
}

#[macro_export]
macro_rules! klog {
    ($($arg:tt)*) => {{
        use core::fmt::Write;
        let _ = writeln!($crate::serial::Serial, $($arg)*);
    }};
}
