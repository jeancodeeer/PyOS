/* PyWin example: four threads add to a shared counter under a lock,
   one waits on an event, and the main thread waits for all of them. */
#include <stdio.h>
#include <windows.h>

static CRITICAL_SECTION lock;
static long total = 0;
static HANDLE go;

DWORD WINAPI worker(LPVOID arg) {
    int n = (int)(INT_PTR)arg;
    WaitForSingleObject(go, INFINITE);          /* everybody starts together */
    for (int i = 0; i < 1000; i++) {
        EnterCriticalSection(&lock);
        total += 1;
        LeaveCriticalSection(&lock);
        if (i % 250 == 0) Sleep(1);
    }
    EnterCriticalSection(&lock);
    printf("hilo %d (id %lu) terminado\n", n, GetCurrentThreadId());
    LeaveCriticalSection(&lock);
    return 100 + n;
}

int main(void) {
    HANDLE t[4];
    InitializeCriticalSection(&lock);
    go = CreateEvent(NULL, TRUE, FALSE, NULL);
    for (int i = 0; i < 4; i++) t[i] = CreateThread(NULL, 0, worker, (LPVOID)(INT_PTR)i, 0, NULL);
    printf("4 hilos creados; empiezan ya\n");
    SetEvent(go);
    WaitForMultipleObjects(4, t, TRUE, INFINITE);
    DWORD sum = 0, code;
    for (int i = 0; i < 4; i++) { GetExitCodeThread(t[i], &code); sum += code; CloseHandle(t[i]); }
    printf("total = %ld (esperado 4000), codigos = %lu\n", total, sum);
    DeleteCriticalSection(&lock);
    return total == 4000 ? 0 : 1;
}
