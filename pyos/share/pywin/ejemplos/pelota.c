/* PyWin example: an animation with a timer, double buffering and the keyboard. */
#include <windows.h>
#define W 400
#define H 300
static int bx = 50, by = 60, dx = 4, dy = 3, px = 160, score = 0;

static void draw(HDC dc) {
    HDC mem = CreateCompatibleDC(dc);                       /* draw off screen, then copy */
    HBITMAP bmp = CreateCompatibleBitmap(dc, W, H);
    HGDIOBJ old = SelectObject(mem, bmp);
    RECT all = {0, 0, W, H};
    HBRUSH sky = CreateSolidBrush(RGB(20, 30, 60));
    FillRect(mem, &all, sky); DeleteObject(sky);
    HBRUSH ball = CreateSolidBrush(RGB(255, 200, 40));
    SelectObject(mem, ball); SelectObject(mem, GetStockObject(NULL_PEN));
    Ellipse(mem, bx - 10, by - 10, bx + 10, by + 10);
    HBRUSH pad = CreateSolidBrush(RGB(90, 200, 255));
    SelectObject(mem, pad);
    Rectangle(mem, px, H - 20, px + 80, H - 10);
    char t[64]; wsprintfA(t, "Puntos: %d   (flechas: mover, Esc: salir)", score);
    SetBkMode(mem, TRANSPARENT); SetTextColor(mem, RGB(255, 255, 255));
    TextOutA(mem, 10, 8, t, lstrlenA(t));
    BitBlt(dc, 0, 0, W, H, mem, 0, 0, SRCCOPY);
    SelectObject(mem, old); DeleteObject(bmp); DeleteObject(ball); DeleteObject(pad); DeleteDC(mem);
}

LRESULT CALLBACK proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_CREATE: SetTimer(h, 1, 30, NULL); return 0;
    case WM_TIMER:
        bx += dx; by += dy;
        if (bx < 10 || bx > W - 10) dx = -dx;
        if (by < 10) dy = -dy;
        if (by > H - 30 && bx > px && bx < px + 80 && dy > 0) { dy = -dy; score++; }
        if (by > H) { by = 60; bx = 50; score = 0; }
        InvalidateRect(h, NULL, FALSE); return 0;
    case WM_KEYDOWN:
        if (w == VK_LEFT && px > 0) px -= 20;
        if (w == VK_RIGHT && px < W - 80) px += 20;
        if (w == VK_ESCAPE) DestroyWindow(h);
        return 0;
    case WM_PAINT: { PAINTSTRUCT ps; HDC dc = BeginPaint(h, &ps); draw(dc); EndPaint(h, &ps); return 0; }
    case WM_CLOSE:
        if (MessageBoxA(h, "Salir del juego?", "Pelota", MB_YESNO | MB_ICONQUESTION) == IDYES) DestroyWindow(h);
        return 0;
    case WM_DESTROY: KillTimer(h, 1); PostQuitMessage(score); return 0;
    }
    return DefWindowProcA(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = proc; wc.hInstance = inst; wc.lpszClassName = "Pelota";
    RegisterClassA(&wc);
    RECT r = {0, 0, W, H};
    AdjustWindowRect(&r, WS_OVERLAPPEDWINDOW, FALSE);
    HWND h = CreateWindowA("Pelota", "Pelota (Win32)", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                           CW_USEDEFAULT, CW_USEDEFAULT, r.right - r.left, r.bottom - r.top, NULL, NULL, inst, NULL);
    MSG m;
    while (GetMessageA(&m, NULL, 0, 0) > 0) { TranslateMessage(&m); DispatchMessageA(&m); }
    return (int)m.wParam;
}
