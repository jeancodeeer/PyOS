// _media: the "arena", a piece of RAM outside the Python heap that the
// JavaScript engine (QuickJS) allocates from with malloc(). Python hands it
// over once with _media.arena(address, size); the garbage collector never
// moves or frees it. (The audio, video and picture decoders are Python now:
// pyos/lib/media/ and pyos/lib/imaging/.)
#include "py/runtime.h"
#include "py/obj.h"

void arena_set(uintptr_t addr, size_t size);
int arena_ready(void);
size_t arena_free_bytes(void);

int abs(int x) {
    return x < 0 ? -x : x;
}

static mp_obj_t media_arena(mp_obj_t addr, mp_obj_t size) {
    if (!arena_ready()) {
        arena_set((uintptr_t)mp_obj_get_int_truncated(addr), (size_t)mp_obj_get_int_truncated(size));
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(media_arena_obj, media_arena);

static mp_obj_t media_arena_free(void) {
    return mp_obj_new_int_from_uint(arena_free_bytes());
}
static MP_DEFINE_CONST_FUN_OBJ_0(media_arena_free_obj, media_arena_free);

static const mp_rom_map_elem_t media_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__media) },
    { MP_ROM_QSTR(MP_QSTR_arena), MP_ROM_PTR(&media_arena_obj) },
    { MP_ROM_QSTR(MP_QSTR_arena_free), MP_ROM_PTR(&media_arena_free_obj) },
};
static MP_DEFINE_CONST_DICT(media_globals, media_globals_table);

const mp_obj_module_t mp_module_media = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&media_globals,
};

MP_REGISTER_MODULE(MP_QSTR__media, mp_module_media);
