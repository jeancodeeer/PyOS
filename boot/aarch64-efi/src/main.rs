//! BOOTAA64.EFI: the SnakeyOS loader for ARM64 machines with UEFI firmware
//! (QEMU's `virt` with AAVMF, servers, Raspberry Pi 4/5 with UEFI firmware...).
//!
//! It does what GRUB and Multiboot do on PCs:
//!   - picks a screen mode (GOP) and notes the framebuffer;
//!   - reads \snakeyos\kernel.elf (a position-independent ELF) and
//!     \snakeyos\pyfs.img (the boot archive) from the boot medium;
//!   - loads the kernel wherever RAM is free and relocates it;
//!   - notes the ACPI tables, the time of day and the memory map;
//!   - leaves the firmware (ExitBootServices) and jumps to the kernel with
//!     x0 = the BootInfo below (rust/arm64/boot.rs reads it).
#![no_std]
#![no_main]

use core::ptr::{null_mut, read_unaligned as rd};

type Status = usize;
type Handle = *mut u8;
const SUCCESS: Status = 0;

#[repr(C)]
struct Guid(u32, u16, u16, [u8; 8]);

const GOP_GUID: Guid = Guid(0x9042a9de, 0x23dc, 0x4a38, [0x96, 0xfb, 0x7a, 0xde, 0xd0, 0x80, 0x51, 0x6a]);
const LOADED_IMAGE_GUID: Guid = Guid(0x5b1b31a1, 0x9562, 0x11d2, [0x8e, 0x3f, 0x00, 0xa0, 0xc9, 0x69, 0x72, 0x3b]);
const SFS_GUID: Guid = Guid(0x964e5b22, 0x6459, 0x11d2, [0x8e, 0x39, 0x00, 0xa0, 0xc9, 0x69, 0x72, 0x3b]);
const ACPI20_GUID: Guid = Guid(0x8868e871, 0xe4f1, 0x11d3, [0xbc, 0x22, 0x00, 0x80, 0xc7, 0x3c, 0x88, 0x81]);

/// What the kernel gets (keep in step with rust/arm64/boot.rs).
#[repr(C)]
pub struct BootInfo {
    magic: u64,             // "SNAKEARM"
    kernel_base: u64,
    kernel_end: u64,
    initrd_start: u64,
    initrd_end: u64,
    fb_addr: u64,
    fb_width: u64,
    fb_height: u64,
    fb_pitch: u64,          // bytes per row
    fb_format: u64,         // 0 RGBx, 1 BGRx (as UEFI's PixelFormat)
    rsdp: u64,
    epoch: u64,             // seconds since 1970 when the loader ran
    mmap: u64,
    mmap_size: u64,
    mmap_desc: u64,
}

static mut ST: *const u8 = null_mut();

unsafe fn at<T>(base: *const u8, off: usize) -> T {
    rd(base.add(off) as *const T)
}
unsafe fn bs() -> *const u8 {
    at::<*const u8>(ST, 96)
}
unsafe fn bs_fn<F>(off: usize) -> F {
    core::mem::transmute_copy::<usize, F>(&at::<usize>(bs(), off))
}

fn wstr(s: &str, out: &mut [u16]) {
    let mut i = 0;
    for b in s.bytes() {
        if i + 2 >= out.len() {
            break;
        }
        if b == b'\n' {
            out[i] = b'\r' as u16;
            i += 1;
        }
        out[i] = b as u16;
        i += 1;
    }
    out[i] = 0;
}

fn say(s: &str) {
    unsafe {
        let con = at::<*const u8>(ST, 64);
        if con.is_null() {
            return;
        }
        let out: extern "efiapi" fn(*const u8, *const u16) -> Status = core::mem::transmute(at::<usize>(con, 8));
        let mut buf = [0u16; 256];
        wstr(s, &mut buf);
        out(con, buf.as_ptr());
    }
}

fn hex(mut v: u64, out: &mut [u8; 18]) -> &str {
    out[0] = b'0';
    out[1] = b'x';
    for i in 0..16 {
        let d = (v >> 60) as u8;
        out[2 + i] = if d < 10 { b'0' + d } else { b'a' + d - 10 };
        v <<= 4;
    }
    unsafe { core::str::from_utf8_unchecked(&out[..]) }
}

fn fail(what: &str) -> ! {
    say("\nSnakeyOS loader: ");
    say(what);
    say("\nCannot continue.\n");
    loop {
        unsafe { core::arch::asm!("wfi") };
    }
}

unsafe fn locate(guid: &Guid) -> *const u8 {
    let f: extern "efiapi" fn(*const Guid, *const u8, *mut *const u8) -> Status = bs_fn(320);
    let mut p: *const u8 = null_mut();
    if f(guid, null_mut(), &mut p) != SUCCESS {
        return null_mut();
    }
    p
}

unsafe fn handle_protocol(h: Handle, guid: &Guid) -> *const u8 {
    let f: extern "efiapi" fn(Handle, *const Guid, *mut *const u8) -> Status = bs_fn(152);
    let mut p: *const u8 = null_mut();
    if f(h, guid, &mut p) != SUCCESS {
        return null_mut();
    }
    p
}

unsafe fn alloc_pages(bytes: u64) -> *mut u8 {
    // AllocatePages(AllocateAnyPages, EfiLoaderData, pages, &addr)
    let f: extern "efiapi" fn(u32, u32, usize, *mut u64) -> Status = bs_fn(40);
    let mut addr = 0u64;
    if f(0, 2, ((bytes + 0xFFF) >> 12) as usize, &mut addr) != SUCCESS {
        fail("out of memory");
    }
    addr as *mut u8
}

/// The screen: 1024x768 if the firmware offers it, else the closest mode not
/// bigger than 1920x1080, else whatever is on now.
unsafe fn screen(info: &mut BootInfo) {
    let gop = locate(&GOP_GUID);
    if gop.is_null() {
        say("SnakeyOS loader: no graphics (GOP); text console on the serial port\n");
        return;
    }
    let query: extern "efiapi" fn(*const u8, u32, *mut usize, *mut *const u8) -> Status = core::mem::transmute(at::<usize>(gop, 0));
    let set: extern "efiapi" fn(*const u8, u32) -> Status = core::mem::transmute(at::<usize>(gop, 8));
    let mode = at::<*const u8>(gop, 24);
    let max = at::<u32>(mode, 0);
    let (mut best, mut best_score) = (u32::MAX, u64::MAX);
    for m in 0..max {
        let mut size = 0usize;
        let mut mi: *const u8 = null_mut();
        if query(gop, m, &mut size, &mut mi) != SUCCESS {
            continue;
        }
        let (w, h, fmt) = (at::<u32>(mi, 4) as u64, at::<u32>(mi, 8) as u64, at::<u32>(mi, 12));
        if fmt > 1 || w > 1920 || h > 1080 || w < 640 {
            continue;
        }
        let score = (w as i64 - 1024).unsigned_abs() + (h as i64 - 768).unsigned_abs();
        if score < best_score {
            best_score = score;
            best = m;
        }
    }
    if best != u32::MAX && best != at::<u32>(mode, 4) {
        set(gop, best);
    }
    let mode = at::<*const u8>(gop, 24);
    let mi = at::<*const u8>(mode, 8);
    let fmt = at::<u32>(mi, 12);
    if fmt > 1 {
        say("SnakeyOS loader: the screen has no linear framebuffer; serial console only\n");
        return;
    }
    info.fb_addr = at::<u64>(mode, 24);
    info.fb_width = at::<u32>(mi, 4) as u64;
    info.fb_height = at::<u32>(mi, 8) as u64;
    info.fb_pitch = at::<u32>(mi, 32) as u64 * 4;
    info.fb_format = fmt as u64;
}

/// The whole file \snakeyos\<name> from the boot medium: (address, size).
unsafe fn read_file(root: *const u8, name: &str) -> (*mut u8, u64) {
    let open: extern "efiapi" fn(*const u8, *mut *const u8, *const u16, u64, u64) -> Status = core::mem::transmute(at::<usize>(root, 8));
    let mut path = [0u16; 64];
    wstr(name, &mut path);
    let mut f: *const u8 = null_mut();
    if open(root, &mut f, path.as_ptr(), 1, 0) != SUCCESS {
        fail(name);
    }
    let read: extern "efiapi" fn(*const u8, *mut usize, *mut u8) -> Status = core::mem::transmute(at::<usize>(f, 32));
    let set_pos: extern "efiapi" fn(*const u8, u64) -> Status = core::mem::transmute(at::<usize>(f, 56));
    let get_pos: extern "efiapi" fn(*const u8, *mut u64) -> Status = core::mem::transmute(at::<usize>(f, 48));
    set_pos(f, u64::MAX);
    let mut size = 0u64;
    get_pos(f, &mut size);
    set_pos(f, 0);
    let buf = alloc_pages(size.max(1));
    let mut got = 0u64;
    while got < size {
        let mut n = (size - got) as usize;
        if read(f, &mut n, buf.add(got as usize)) != SUCCESS || n == 0 {
            fail("read error");
        }
        got += n as u64;
    }
    (buf, size)
}

/// Load the ELF kernel at any address and apply its R_AARCH64_RELATIVE
/// relocations. Returns (base, end, entry).
unsafe fn load_kernel(elf: *const u8, len: u64) -> (u64, u64, u64) {
    if len < 64 || at::<u32>(elf, 0) != 0x464c457f || at::<u16>(elf, 18) != 183 {
        fail("kernel.elf is not an ARM64 ELF file");
    }
    let (phoff, phentsize, phnum) = (at::<u64>(elf, 32) as usize, at::<u16>(elf, 54) as usize, at::<u16>(elf, 56) as usize);
    let mut top = 0u64;
    for i in 0..phnum {
        let ph = elf.add(phoff + i * phentsize);
        if at::<u32>(ph, 0) == 1 {
            top = top.max(at::<u64>(ph, 16) + at::<u64>(ph, 40));
        }
    }
    let size = (top + 0xFFFF) & !0xFFFF;
    // 64 KiB aligned (the kernel's sections are page aligned at most)
    let raw = alloc_pages(size + 0x10000) as u64;
    let base = (raw + 0xFFFF) & !0xFFFF;
    core::ptr::write_bytes(base as *mut u8, 0, size as usize);
    let mut dynamic = 0u64;
    for i in 0..phnum {
        let ph = elf.add(phoff + i * phentsize);
        match at::<u32>(ph, 0) {
            1 => {
                let (off, va, filesz) = (at::<u64>(ph, 8), at::<u64>(ph, 16), at::<u64>(ph, 32));
                core::ptr::copy_nonoverlapping(elf.add(off as usize), (base + va) as *mut u8, filesz as usize);
            }
            2 => dynamic = at::<u64>(ph, 16),
            _ => {}
        }
    }
    if dynamic != 0 {
        let (mut rela, mut relasz) = (0u64, 0u64);
        let mut d = (base + dynamic) as *const u64;
        loop {
            let (tag, val) = (*d, *d.add(1));
            match tag {
                0 => break,
                7 => rela = val,
                8 => relasz = val,
                _ => {}
            }
            d = d.add(2);
        }
        let mut r = base + rela;
        let end = r + relasz;
        while rela != 0 && r < end {
            let (off, info, addend) = (*(r as *const u64), *((r + 8) as *const u64), *((r + 16) as *const i64));
            if info & 0xFFFF_FFFF == 1027 {              // R_AARCH64_RELATIVE
                *((base + off) as *mut u64) = base.wrapping_add(addend as u64);
            }
            r += 24;
        }
    }
    (base, base + size, base + at::<u64>(elf, 24))
}

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

unsafe fn epoch() -> u64 {
    let rt = at::<*const u8>(ST, 88);
    let get_time: extern "efiapi" fn(*mut [u8; 16], *mut u8) -> Status = core::mem::transmute(at::<usize>(rt, 24));
    let mut t = [0u8; 16];
    if get_time(&mut t, null_mut()) != SUCCESS {
        return 0;
    }
    let year = u16::from_le_bytes([t[0], t[1]]) as i64;
    let days = days_from_civil(year, t[2] as i64, t[3] as i64);
    (days * 86400 + t[4] as i64 * 3600 + t[5] as i64 * 60 + t[6] as i64) as u64
}

unsafe fn rsdp() -> u64 {
    let n = at::<usize>(ST, 104);
    let table = at::<*const u8>(ST, 112);
    for i in 0..n {
        let e = table.add(i * 24);
        let g = &*(e as *const [u8; 16]);
        let want = &*(&ACPI20_GUID as *const Guid as *const [u8; 16]);
        if g == want {
            return at::<u64>(e, 16);
        }
    }
    0
}

#[no_mangle]
pub extern "efiapi" fn efi_main(image: Handle, st: *const u8) -> Status {
    unsafe {
        ST = st;
        // no watchdog: SetWatchdogTimer(0, ...)
        let wd: extern "efiapi" fn(usize, u64, usize, *const u16) -> Status = bs_fn(256);
        wd(0, 0, 0, null_mut());
        say("SnakeyOS: loading...\n");
        let info = &mut *(alloc_pages(4096) as *mut BootInfo);
        core::ptr::write_bytes(info as *mut BootInfo as *mut u8, 0, core::mem::size_of::<BootInfo>());
        info.magic = u64::from_le_bytes(*b"SNAKEARM");

        let li = handle_protocol(image, &LOADED_IMAGE_GUID);
        if li.is_null() {
            fail("no loaded image protocol");
        }
        let fs = handle_protocol(at::<Handle>(li, 24), &SFS_GUID);
        if fs.is_null() {
            fail("cannot read the boot medium");
        }
        let open_volume: extern "efiapi" fn(*const u8, *mut *const u8) -> Status = core::mem::transmute(at::<usize>(fs, 8));
        let mut root: *const u8 = null_mut();
        if open_volume(fs, &mut root) != SUCCESS {
            fail("cannot open the boot medium");
        }
        let (elf, elf_len) = read_file(root, "\\snakeyos\\kernel.elf");
        let (img, img_len) = read_file(root, "\\snakeyos\\pyfs.img");
        let (base, end, entry) = load_kernel(elf, elf_len);
        info.kernel_base = base;
        info.kernel_end = end;
        info.initrd_start = img as u64;
        info.initrd_end = img as u64 + img_len;
        info.rsdp = rsdp();
        info.epoch = epoch();
        let mut h = [0u8; 18];
        say("SnakeyOS: kernel at ");
        say(hex(base, &mut h));
        say("\n");
        screen(info);

        // the memory map, then leave the firmware (retry once: the map can change)
        let get_map: extern "efiapi" fn(*mut usize, *mut u8, *mut usize, *mut usize, *mut u32) -> Status = bs_fn(56);
        let exit_bs: extern "efiapi" fn(Handle, usize) -> Status = bs_fn(232);
        let cap = 64 * 1024usize;
        let map = alloc_pages(cap as u64);
        for _ in 0..4 {
            let (mut size, mut key, mut desc, mut ver) = (cap, 0usize, 0usize, 0u32);
            if get_map(&mut size, map, &mut key, &mut desc, &mut ver) != SUCCESS {
                fail("no memory map");
            }
            info.mmap = map as u64;
            info.mmap_size = size as u64;
            info.mmap_desc = desc as u64;
            if exit_bs(image, key) == SUCCESS {
                core::arch::asm!("msr daifset, #0xf", "isb");
                let kernel: extern "C" fn(*const BootInfo) -> ! = core::mem::transmute(entry);
                kernel(info);
            }
        }
        fail("ExitBootServices failed");
    }
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! {
    fail("loader panic")
}
