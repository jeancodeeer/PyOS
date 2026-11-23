#include <stdio.h>
int main(void) {
    char nombre[64]; int edad;
    printf("Como te llamas? ");
    if (scanf("%63s", nombre) != 1) return 1;
    printf("Cuantos anos tienes? ");
    if (scanf("%d", &edad) != 1) return 2;
    printf("Hola %s, en 10 anos tendras %d.\n", nombre, edad + 10);
    return 0;
}
