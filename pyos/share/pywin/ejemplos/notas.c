/* PyWin example: a small notepad. Its menu and texts come from resources
   (notas.rc), it uses the Open/Save dialogs, files and the registry. */
#include <windows.h>
#include <stdio.h>
#define ID_NUEVO 101
#define ID_ABRIR 102
#define ID_GUARDAR 103
#define ID_SALIR 104
#define ID_AJUSTE 201
#define ID_ACERCA 301
#define ID_TEXTO 1

static HWND texto;
static char titulo[64];

static void recordar(const char *ruta) {               /* the registry keeps the last file */
    HKEY k;
    if (RegCreateKeyExA(HKEY_CURRENT_USER, "Software\\PyWin\\Notas", 0, NULL, 0, KEY_WRITE, NULL, &k, NULL) == 0) {
        RegSetValueExA(k, "Ultimo", 0, REG_SZ, (const BYTE *)ruta, lstrlenA(ruta) + 1);
        DWORD veces = 0, n = sizeof veces;
        RegQueryValueExA(k, "Veces", NULL, NULL, (BYTE *)&veces, &n);
        veces++;
        RegSetValueExA(k, "Veces", 0, REG_DWORD, (const BYTE *)&veces, sizeof veces);
        RegCloseKey(k);
    }
}

static void abrir(HWND h, int guardar) {
    char ruta[260] = "nota.txt";
    OPENFILENAMEA of = {0};
    of.lStructSize = sizeof of; of.hwndOwner = h; of.lpstrFile = ruta; of.nMaxFile = sizeof ruta;
    of.lpstrFilter = "Texto\0*.txt\0";
    if (!(guardar ? GetSaveFileNameA(&of) : GetOpenFileNameA(&of))) return;
    HANDLE f = CreateFileA(ruta, guardar ? GENERIC_WRITE : GENERIC_READ, 0, NULL,
                           guardar ? CREATE_ALWAYS : OPEN_EXISTING, 0, NULL);
    if (f == INVALID_HANDLE_VALUE) { MessageBoxA(h, "No se puede abrir el archivo", titulo, MB_ICONERROR); return; }
    static char buf[4096];
    DWORD n = 0;
    if (guardar) { n = GetWindowTextA(texto, buf, sizeof buf); WriteFile(f, buf, n, &n, NULL); }
    else { ReadFile(f, buf, sizeof buf - 1, &n, NULL); buf[n] = 0; SetWindowTextA(texto, buf); }
    CloseHandle(f);
    recordar(ruta);
}

LRESULT CALLBACK proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_CREATE:
        texto = CreateWindowA("EDIT", "", WS_CHILD | WS_VISIBLE | ES_MULTILINE, 0, 0, 100, 100,
                              h, (HMENU)ID_TEXTO, NULL, NULL);
        SetFocus(texto);
        return 0;
    case WM_SIZE:
        MoveWindow(texto, 4, 4, LOWORD(l) - 8, HIWORD(l) - 8, TRUE);
        return 0;
    case WM_COMMAND:
        switch (LOWORD(w)) {
        case ID_NUEVO: SetWindowTextA(texto, ""); break;
        case ID_ABRIR: abrir(h, 0); break;
        case ID_GUARDAR: abrir(h, 1); break;
        case ID_SALIR: DestroyWindow(h); break;
        case ID_AJUSTE: {
            HMENU menu = GetMenu(h);
            UINT antes = CheckMenuItem(menu, ID_AJUSTE, MF_BYCOMMAND | MF_UNCHECKED);
            if (antes != MF_CHECKED) CheckMenuItem(menu, ID_AJUSTE, MF_BYCOMMAND | MF_CHECKED);
            break; }
        case ID_ACERCA: {
            char texto2[200];
            LoadStringA(GetModuleHandleA(NULL), 2, texto2, sizeof texto2);
            MessageBoxA(h, texto2, titulo, MB_OK | MB_ICONINFORMATION);
            break; }
        }
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    LoadStringA(inst, 1, titulo, sizeof titulo);
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = proc; wc.hInstance = inst; wc.lpszClassName = "Notas";
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    RegisterClassA(&wc);
    HWND h = CreateWindowA("Notas", titulo, WS_OVERLAPPEDWINDOW | WS_VISIBLE, CW_USEDEFAULT, CW_USEDEFAULT,
                           480, 320, NULL, LoadMenuA(inst, "MENU_PRINCIPAL"), inst, NULL);
    MSG msg;
    while (GetMessageA(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    return 0;
}
