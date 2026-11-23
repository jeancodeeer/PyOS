/* PyWin example: an OpenGL program for Windows (WGL + GL + GLU): a lit,
   spinning cube and a sphere. Arrows change the speed; Esc quits. */
#include <windows.h>
#include <GL/gl.h>
#include <GL/glu.h>

static HDC dc;
static float angulo = 0, velocidad = 3;
static GLUquadric *esfera;

static void escena(int w, int h) {
    glViewport(0, 0, w, h);
    glMatrixMode(GL_PROJECTION); glLoadIdentity();
    gluPerspective(45.0, (double)w / (h ? h : 1), 0.5, 50.0);
    glMatrixMode(GL_MODELVIEW);
}

static void dibujar(void) {
    static const float caras[6][3] = {{1,.3f,.3f},{.3f,1,.3f},{.3f,.5f,1},{1,.9f,.2f},{.9f,.4f,1},{.3f,1,1}};
    static const float n[6][3] = {{0,0,1},{0,0,-1},{1,0,0},{-1,0,0},{0,1,0},{0,-1,0}};
    static const float v[6][4][3] = {
        {{-1,-1,1},{1,-1,1},{1,1,1},{-1,1,1}}, {{1,-1,-1},{-1,-1,-1},{-1,1,-1},{1,1,-1}},
        {{1,-1,1},{1,-1,-1},{1,1,-1},{1,1,1}}, {{-1,-1,-1},{-1,-1,1},{-1,1,1},{-1,1,-1}},
        {{-1,1,1},{1,1,1},{1,1,-1},{-1,1,-1}}, {{-1,-1,-1},{1,-1,-1},{1,-1,1},{-1,-1,1}}};
    glClearColor(0.05f, 0.06f, 0.12f, 1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glLoadIdentity();
    glTranslatef(0, 0, -8);
    float luz[4] = {3, 4, 5, 1};
    glLightfv(GL_LIGHT0, GL_POSITION, luz);
    glPushMatrix();
    glTranslatef(-1.3f, 0, 0);
    glRotatef(angulo, 1, 1, 0);
    glBegin(GL_QUADS);
    for (int f = 0; f < 6; f++) {
        glNormal3fv(n[f]); glColor3fv(caras[f]);
        for (int k = 0; k < 4; k++) glVertex3fv(v[f][k]);
    }
    glEnd();
    glPopMatrix();
    glPushMatrix();
    glTranslatef(1.8f, 0, 0);
    glColor3f(1, 0.8f, 0.3f);
    gluSphere(esfera, 1.0, 16, 12);
    glPopMatrix();
    SwapBuffers(dc);
}

LRESULT CALLBACK proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_SIZE: escena(LOWORD(l), HIWORD(l)); return 0;
    case WM_TIMER: angulo += velocidad; dibujar(); return 0;
    case WM_KEYDOWN:
        if (w == VK_UP) velocidad += 1;
        if (w == VK_DOWN && velocidad > 0) velocidad -= 1;
        if (w == VK_ESCAPE) DestroyWindow(h);
        return 0;
    case WM_DESTROY: PostQuitMessage(0); return 0;
    }
    return DefWindowProcA(h, m, w, l);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    WNDCLASSA wc = {0};
    wc.style = CS_OWNDC; wc.lpfnWndProc = proc; wc.hInstance = inst; wc.lpszClassName = "CuboGL";
    RegisterClassA(&wc);
    HWND h = CreateWindowA("CuboGL", "OpenGL en PyWin", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                           CW_USEDEFAULT, CW_USEDEFAULT, 480, 360, NULL, NULL, inst, NULL);
    dc = GetDC(h);
    PIXELFORMATDESCRIPTOR pfd = {sizeof pfd, 1, PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER,
                                 PFD_TYPE_RGBA, 32};
    pfd.cDepthBits = 24;
    SetPixelFormat(dc, ChoosePixelFormat(dc, &pfd), &pfd);
    HGLRC rc = wglCreateContext(dc);
    wglMakeCurrent(dc, rc);
    glEnable(GL_DEPTH_TEST); glEnable(GL_LIGHTING); glEnable(GL_LIGHT0); glEnable(GL_COLOR_MATERIAL);
    esfera = gluNewQuadric();
    RECT r; GetClientRect(h, &r); escena(r.right, r.bottom);
    SetTimer(h, 1, 40, NULL);
    MSG msg;
    while (GetMessageA(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    gluDeleteQuadric(esfera);
    wglMakeCurrent(NULL, NULL); wglDeleteContext(rc);
    return 0;
}
