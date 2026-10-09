/* Diagnostic-only: initialize ASan, then restore the environment for children.
 * No libc dependency is linked: these symbols resolve in the glibc guest. */
extern void __asan_init(void);
extern char *getenv(const char *);
extern int setenv(const char *, const char *, int);
extern int unsetenv(const char *);

__attribute__((constructor)) static void restore_child_environment(void)
{
    /* Parse diagnostic ASAN_OPTIONS before restoring child process variables. */
    __asan_init();
    const char *preload = getenv("PIXEL_ASAN_CHILD_PRELOAD");
    const char *libraries = getenv("PIXEL_ASAN_CHILD_LIBRARY_PATH");
    if (preload && *preload) setenv("LD_PRELOAD", preload, 1);
    else unsetenv("LD_PRELOAD");
    if (libraries && *libraries) setenv("LD_LIBRARY_PATH", libraries, 1);
    else unsetenv("LD_LIBRARY_PATH");
    unsetenv("ASAN_OPTIONS");
    unsetenv("PIXEL_ASAN_CHILD_PRELOAD");
    unsetenv("PIXEL_ASAN_CHILD_LIBRARY_PATH");
}
