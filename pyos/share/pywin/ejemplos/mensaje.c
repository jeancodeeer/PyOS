#include <windows.h>
int WINAPI WinMain(HINSTANCE h, HINSTANCE p, LPSTR cmd, int show) {
    int r = MessageBoxA(NULL, "Hola desde Win32", "PyWin", MB_OKCANCEL | MB_ICONINFORMATION);
    return r == IDOK ? 0 : 1;
}
