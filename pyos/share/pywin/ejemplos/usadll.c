/* PyWin example: a program that uses milib.dll in both ways: linked at
   build time (import table) and found while running (LoadLibrary). */
#include <windows.h>
#include <stdio.h>
__declspec(dllimport) int suma(int, int);
__declspec(dllimport) const char *saludo(void);
typedef int (*contador_fn)(void);
int main(void) {
    printf("%s\n", saludo());
    printf("suma(20, 22) = %d\n", suma(20, 22));
    HMODULE m = LoadLibraryA("milib.dll");
    contador_fn contador = (contador_fn)GetProcAddress(m, "contador");
    printf("LoadLibrary: %s, contador() = %d\n", m ? "ok" : "no", contador ? contador() : -1);
    return 0;
}
