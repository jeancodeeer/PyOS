// malloc / free / realloc over the "arena": a big piece of RAM, outside
// Python's heap, for the C code that wants a C allocator (the video and
// picture decoders, and the JavaScript engine, which makes and drops
// hundreds of thousands of small objects).
//
// Segregated fit: free blocks wait in bins by size. Blocks up to 1 KiB
// have a bin per 16-byte size (taken in O(1)); bigger ones a bin per
// quarter of a power of two. A bitmap finds the next bin that is not
// empty. Every block knows its size, and a free block also writes it at
// its end, so a freed block joins its free neighbours at once.
//
//   [size | flags] [magic] [ payload ...                     ]
//   free payload:  [next] [prev] ...................... [size]
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define HDR 16
#define MIN_PAYLOAD 32
#define USED 1u
#define PREV_FREE 2u
#define MAGIC 0xA11CB10Cu
#define NBINS 128
#define SMALL 1024

typedef struct hdr {
    size_t size;                // payload bytes, a multiple of 16
    uint32_t flags;
    uint32_t magic;
} hdr_t;

typedef struct {
    hdr_t *next, *prev;
} links_t;

static hdr_t *bins[NBINS];
static uint64_t bitmap[NBINS / 64];
static uintptr_t lo, hi;
static volatile int lock;

static inline void take_lock(void) {
    while (__atomic_exchange_n(&lock, 1, __ATOMIC_ACQUIRE)) {
        __asm__ volatile ("pause");
    }
}

static inline void drop_lock(void) {
    __atomic_store_n(&lock, 0, __ATOMIC_RELEASE);
}

static inline links_t *links(hdr_t *b) {
    return (links_t *)((uint8_t *)b + HDR);
}

static inline hdr_t *next_block(hdr_t *b) {
    return (hdr_t *)((uint8_t *)b + HDR + b->size);
}

static inline void set_footer(hdr_t *b) {
    *(size_t *)((uint8_t *)b + HDR + b->size - sizeof(size_t)) = b->size;
}

static inline int log2_floor(size_t n) {
    return 63 - __builtin_clzll((unsigned long long)n);
}

static int bin_of(size_t size) {
    if (size < SMALL) {
        return (int)(size >> 4);                        // 2..63: one size each
    }
    int l = log2_floor(size);                           // 10 and up
    int i = 64 + (l - 10) * 4 + (int)((size >> (l - 2)) & 3);
    return i < NBINS ? i : NBINS - 1;
}

static void bin_insert(hdr_t *b) {
    int i = bin_of(b->size);
    links_t *l = links(b);
    l->prev = NULL;
    l->next = bins[i];
    if (bins[i]) {
        links(bins[i])->prev = b;
    }
    bins[i] = b;
    bitmap[i >> 6] |= 1ull << (i & 63);
}

static void bin_remove(hdr_t *b) {
    int i = bin_of(b->size);
    links_t *l = links(b);
    if (l->prev) {
        links(l->prev)->next = l->next;
    } else {
        bins[i] = l->next;
        if (!bins[i]) {
            bitmap[i >> 6] &= ~(1ull << (i & 63));
        }
    }
    if (l->next) {
        links(l->next)->prev = l->prev;
    }
}

// a free block: in its bin, with its footer, and its right neighbour knows
static void make_free(hdr_t *b) {
    b->flags &= ~USED;
    set_footer(b);
    next_block(b)->flags |= PREV_FREE;
    bin_insert(b);
}

void arena_set(uintptr_t addr, size_t size) {
    addr = (addr + 15) & ~(uintptr_t)15;
    size &= ~(size_t)15;
    lo = addr;
    hi = addr + size;
    hdr_t *b = (hdr_t *)addr;
    b->size = size - 2 * HDR;                           // the rest, minus the end marker
    b->flags = 0;
    b->magic = MAGIC;
    hdr_t *end = next_block(b);                         // a used block of size 0: nothing joins past it
    end->size = 0;
    end->flags = USED;
    end->magic = MAGIC;
    make_free(b);
}

int arena_ready(void) {
    return lo != 0;
}

// cut b to `size`; the rest (if worth it) becomes a free block
static void split(hdr_t *b, size_t size) {
    if (b->size < size + HDR + MIN_PAYLOAD) {
        return;
    }
    hdr_t *rest = (hdr_t *)((uint8_t *)b + HDR + size);
    rest->size = b->size - size - HDR;
    rest->flags = 0;
    rest->magic = MAGIC;
    b->size = size;
    hdr_t *after = next_block(rest);
    if (!(after->flags & USED)) {                       // join with a free block behind it
        bin_remove(after);
        after->magic = 0;
        rest->size += HDR + after->size;
    }
    make_free(rest);
}

static inline size_t round_size(size_t n) {
    n = (n + 15) & ~(size_t)15;
    return n < MIN_PAYLOAD ? MIN_PAYLOAD : n;
}

static hdr_t *find(size_t n) {
    int i = bin_of(n);
    if (i >= 64) {                                      // a range bin: some blocks may be too small
        for (hdr_t *b = bins[i]; b; b = links(b)->next) {
            if (b->size >= n) {
                return b;
            }
        }
        i++;
    } else if (bins[i]) {
        return bins[i];
    } else {
        i++;
    }
    for (int w = i >> 6; w < NBINS / 64; w++) {         // the next bin with something in it
        uint64_t m = bitmap[w];
        if (w == i >> 6) {
            m &= ~0ull << (i & 63);
        }
        if (m) {
            return bins[w * 64 + __builtin_ctzll(m)];
        }
    }
    return NULL;
}

void *malloc(size_t n) {
    if (!lo || n > hi - lo) {
        return NULL;
    }
    n = round_size(n);
    take_lock();
    hdr_t *b = find(n);
    if (b) {
        bin_remove(b);
        b->flags |= USED;
        next_block(b)->flags &= ~PREV_FREE;
        split(b, n);
    }
    drop_lock();
    return b ? (uint8_t *)b + HDR : NULL;
}

static hdr_t *block_of(void *p) {
    if (!p || (uintptr_t)p < lo + HDR || (uintptr_t)p >= hi) {
        return NULL;
    }
    hdr_t *b = (hdr_t *)((uint8_t *)p - HDR);
    if (b->magic != MAGIC || !(b->flags & USED)) {
        return NULL;                                    // not ours, or freed twice
    }
    return b;
}

void free(void *p) {
    take_lock();
    hdr_t *b = block_of(p);
    if (b) {
        hdr_t *next = next_block(b);
        if (!(next->flags & USED)) {                    // join the free block after
            bin_remove(next);
            next->magic = 0;                            // a header inside another block: not a block any more
            b->size += HDR + next->size;
        }
        if (b->flags & PREV_FREE) {                     // and the free block before
            size_t prev_size = *(size_t *)((uint8_t *)b - sizeof(size_t));
            hdr_t *prev = (hdr_t *)((uint8_t *)b - prev_size - HDR);
            bin_remove(prev);
            prev->size += HDR + b->size;
            b->magic = 0;
            b = prev;
        }
        make_free(b);
    }
    drop_lock();
}

void *calloc(size_t n, size_t size) {
    if (size && n > ((size_t)-1) / size) {
        return NULL;
    }
    void *p = malloc(n * size);
    if (p) {
        memset(p, 0, n * size);
    }
    return p;
}

void *realloc(void *p, size_t n) {
    if (!p) {
        return malloc(n);
    }
    size_t want = round_size(n);
    take_lock();
    hdr_t *b = block_of(p);
    if (!b) {
        drop_lock();
        return NULL;
    }
    if (b->size >= want) {                              // fits: give back what is left over
        split(b, want);
        drop_lock();
        return p;
    }
    hdr_t *next = next_block(b);
    if (!(next->flags & USED) && b->size + HDR + next->size >= want) {   // grow into the free neighbour
        bin_remove(next);
        next->magic = 0;
        b->size += HDR + next->size;
        next_block(b)->flags &= ~PREV_FREE;
        split(b, want);
        drop_lock();
        return p;
    }
    size_t old = b->size;
    drop_lock();
    void *q = malloc(n);
    if (q) {
        memcpy(q, p, old);
        free(p);
    }
    return q;
}

size_t malloc_usable_size(void *p) {
    hdr_t *b = block_of(p);
    return b ? b->size : 0;
}

size_t arena_free_bytes(void) {
    size_t total = 0;
    take_lock();
    for (int i = 0; i < NBINS; i++) {
        for (hdr_t *b = bins[i]; b; b = links(b)->next) {
            total += b->size;
        }
    }
    drop_lock();
    return total;
}
