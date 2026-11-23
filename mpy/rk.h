// Primitives implemented by the Rust layer (rust/*.rs).
#ifndef PYKERNEL_RK_H
#define PYKERNEL_RK_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

uint8_t rk_inb(uint16_t port);
uint16_t rk_inw(uint16_t port);
uint32_t rk_inl(uint16_t port);
void rk_outb(uint16_t port, uint8_t v);
void rk_outw(uint16_t port, uint16_t v);
void rk_outl(uint16_t port, uint32_t v);
void rk_insw(uint16_t port, void *buf, size_t words);
void rk_outsw(uint16_t port, const void *buf, size_t words);

uint64_t rk_irq_save(void);
void rk_irq_restore(uint64_t flags);
void rk_cli(void);
void rk_sti(void);
void rk_sti_hlt(void);
void rk_hlt(void);

uint64_t rk_rdmsr(uint32_t msr);
void rk_wrmsr(uint32_t msr, uint64_t v);
void rk_cpuid(uint32_t leaf, uint32_t sub, uint32_t *out4);
uint64_t rk_rdtsc(void);
uint64_t rk_read_cr(uint32_t n);
void rk_write_cr(uint32_t n, uint64_t v);
void rk_invlpg(uint64_t addr);
uint64_t rk_call(uint64_t addr, uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e, uint64_t f);

void rk_preempt(uint32_t vector, uint32_t slice_ticks);
int rk_thread_create(uint64_t entry, uint64_t arg, uint64_t stack, uint64_t size);
uint32_t rk_thread_current(void);
void rk_thread_yield(void);
void rk_thread_wait(uint64_t flags);
void rk_thread_exit(void) __attribute__((noreturn));
bool rk_thread_stack(uint32_t i, uint64_t *sp, uint64_t *top);
bool rk_thread_info(uint32_t i, uint64_t *out3);
void mpk_gc_other_threads(void);
uint64_t rk_thread_tls(uint32_t i);
size_t rk_klog(uint8_t *out, size_t cap);

void rk_irq_arm(uint32_t vector, bool on);
void rk_irq_ack(uint32_t vector);
uint64_t rk_irq_count(uint32_t vector);
uint64_t rk_irq_dropped(void);
bool rk_irq_fifo(uint32_t vector, uint16_t status, uint8_t mask, uint8_t value, uint16_t data);
size_t rk_irq_fifo_read(uint32_t vector, uint8_t *out, size_t len);
uint64_t rk_irq_fifo_lost(void);

void rk_stdin_push(uint8_t c);
int rk_stdin_pop(void);
bool rk_stdin_empty(void);
int rk_serial_rx(void);
void rk_serial_write(const char *p, size_t len);

uint64_t rk_info(uint32_t index);
void rk_fatal(uint64_t code) __attribute__((noreturn));

// Shared between the two glue files.
void mpk_feed(int c);
void mpk_async_reset(uint32_t id);
void mpk_async_exit(uint32_t id);

#endif
