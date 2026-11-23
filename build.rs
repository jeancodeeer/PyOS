// Generates the 256 interrupt entry stubs and points the linker at the
// MicroPython static library built by tools/build.py (inside WSL).
use std::{env, fmt::Write, fs, path::PathBuf};

fn main() {
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let has_err = |v: u32| matches!(v, 8 | 10..=14 | 17 | 21 | 29 | 30);

    let mut s = String::from(".section .text.isr, \"ax\"\n.code64\n");
    for v in 0..256u32 {
        writeln!(s, "isr_stub_{v}:").unwrap();
        if !has_err(v) {
            s.push_str("    pushq $0\n");
        }
        writeln!(s, "    pushq ${v}\n    jmp isr_common").unwrap();
    }
    s.push_str(".section .rodata.isr, \"a\"\n.balign 8\n.global isr_stub_table\nisr_stub_table:\n");
    for v in 0..256u32 {
        writeln!(s, "    .quad isr_stub_{v}").unwrap();
    }
    fs::write(out.join("isr_stubs.s"), s).unwrap();

    let root = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let lib = root.join("build").join("mpy");
    println!("cargo:rustc-link-search=native={}", lib.display());
    println!("cargo:rustc-link-lib=static=micropython");
    println!("cargo:rerun-if-changed={}", lib.join("libmicropython.a").display());
    println!("cargo:rerun-if-changed=rust/linker.ld");
    println!("cargo:rerun-if-changed=build.rs");
}
