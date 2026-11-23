/* PyWin test: a classic Win32 window with a message loop, GDI and a button. */
#include <windows.h>
static int clicks = 0;
LRESULT CALLBACK WndProc(HWND h, UINT msg, WPARAM w, LPARAM l) {
    switch (msg) {
    case WM_CREATE:
        CreateWindowA("BUTTON", "Pulsame", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 20, 80, 120, 32, h, (HMENU)1, NULL, NULL);
        return 0;
    case WM_COMMAND:
        if (LOWORD(w) == 1) { clicks++; InvalidateRect(h, NULL, TRUE); }
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT ps; HDC dc = BeginPaint(h, &ps);
        RECT r = {10, 10, 300, 60};
        HBRUSH b = CreateSolidBrush(RGB(255, 230, 150));
        FillRect(dc, &r, b); DeleteObject(b);
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, RGB(20, 40, 120));
        char t[64]; wsprintfA(t, "Hola Win32! clics: %d", clicks);
        TextOutA(dc, 20, 25, t, lstrlenA(t));
        Rectangle(dc, 160, 80, 260, 140);
        Ellipse(dc, 170, 90, 250, 130);
        MoveToEx(dc, 10, 150, NULL); LineTo(dc, 300, 150);
        EndPaint(h, &ps);
        return 0; }
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(h, msg, w, l);
}
int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = WndProc; wc.hInstance = inst; wc.lpszClassName = "Demo";
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1); wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    RegisterClassA(&wc);
    HWND h = CreateWindowExA(0, "Demo", "Ventana Win32 en PyWin", WS_OVERLAPPEDWINDOW,
                             CW_USEDEFAULT, CW_USEDEFAULT, 340, 220, NULL, NULL, inst, NULL);
    ShowWindow(h, show); UpdateWindow(h);
    MSG m;
    while (GetMessageA(&m, NULL, 0, 0) > 0) { TranslateMessage(&m); DispatchMessageA(&m); }
    return (int)m.wParam;
}
