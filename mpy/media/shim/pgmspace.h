/* PyKernel: constant tables are ordinary memory here. */
#pragma once
#define PROGMEM
#define pgm_read_byte(p) (*(const unsigned char *)(p))
#define pgm_read_word(p) (*(const unsigned short *)(p))
#define pgm_read_dword(p) (*(const unsigned int *)(p))
#define pgm_read_ptr(p) (*(void * const *)(p))
