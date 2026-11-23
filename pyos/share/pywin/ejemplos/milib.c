/* PyWin example: a DLL of our own. PyWin loads the real file and runs it. */
#include <windows.h>
#include <stdio.h>
static int veces = 0;
BOOL WINAPI DllMain(HINSTANCE h, DWORD razon, LPVOID r) {
    if (razon == DLL_PROCESS_ATTACH) printf("[milib.dll] cargada\n");
    return TRUE;
}
__declspec(dllexport) int suma(int a, int b) { veces++; return a + b; }
__declspec(dllexport) const char *saludo(void) { return "hola desde milib.dll"; }
__declspec(dllexport) int contador(void) { return veces; }
