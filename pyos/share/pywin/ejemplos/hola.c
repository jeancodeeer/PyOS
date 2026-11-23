/* PyWin test: a console program compiled for Windows (MinGW). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

int main(int argc, char **argv) {
    printf("Hola desde un .exe de Windows!\n");
    printf("argc=%d argv[0]=%s\n", argc, argv[0]);
    char *p = malloc(64);
    strcpy(p, "memoria del heap");
    printf("%s, %d, %5.2f, %x, %c\n", p, 42, 3.14159, 255, 'Z');
    free(p);
    DWORD t = GetTickCount();
    printf("GetTickCount=%s\n", t > 0 ? "ok" : "0");
    FILE *f = fopen("pywin.txt", "w");
    if (f) { fprintf(f, "escrito por un exe\n"); fclose(f); }
    f = fopen("pywin.txt", "r");
    char line[64] = {0};
    if (f) { fgets(line, sizeof line, f); fclose(f); }
    printf("leido: %s", line);
    int sum = 0;
    for (int i = 1; i <= 1000000; i++) sum += i % 7;
    printf("bucle nativo: %d\n", sum);
    return 7;
}
