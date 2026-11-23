/* PyWin example: colours in the console, the Windows way and the ANSI way. */
#include <windows.h>
#include <stdio.h>
#include <shlobj.h>
int main(void) {
    HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    const char *nombres[] = {"rojo", "verde", "azul", "amarillo"};
    WORD colores[] = {FOREGROUND_RED | FOREGROUND_INTENSITY, FOREGROUND_GREEN | FOREGROUND_INTENSITY,
                      FOREGROUND_BLUE | FOREGROUND_INTENSITY, FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_INTENSITY};
    for (int i = 0; i < 4; i++) {
        SetConsoleTextAttribute(out, colores[i]);
        printf("%s ", nombres[i]);
    }
    SetConsoleTextAttribute(out, FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_BLUE);
    printf("\n\x1b[35mmagenta (ANSI)\x1b[0m y normal\n");
    HKEY k; DWORD v = 7;
    RegCreateKeyExA(HKEY_CURRENT_USER, "Software\\PyWin\\Prueba", 0, NULL, 0, KEY_ALL_ACCESS, NULL, &k, NULL);
    RegSetValueExA(k, "Numero", 0, REG_DWORD, (BYTE *)&v, 4);
    v = 0; DWORD n = 4;
    RegQueryValueExA(k, "Numero", NULL, NULL, (BYTE *)&v, &n);
    RegCloseKey(k);
    printf("registro: Numero = %lu\n", v);
    char doc[MAX_PATH];
    SHGetFolderPathA(NULL, 5, NULL, 0, doc);
    printf("Documentos: %s\n", doc);
    return 0;
}
