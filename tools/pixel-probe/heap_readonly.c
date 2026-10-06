/* Prototype adapter for PanVK's O_RDWR heap open on Pixel's 0444 heap nodes.
 * libc-free ELF: the same AArch64 ABI works in glibc, with no bionic dependencies.
 * Remove this shim when rebuilding PanVK with O_RDONLY in kbase_kmod.c.
 * Never use as a global preload. */
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <string.h>

static mode_t mode_argument(int flags, va_list args) {
    return (flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE ? va_arg(args, mode_t) : 0;
}

int open64(const char *path, int flags, ...) {
    va_list args;
    va_start(args, flags);
    mode_t mode = mode_argument(flags, args);
    va_end(args);
    int (*next)(const char *, int, ...) = (int (*)(const char *, int, ...))dlsym((void *)-1, "open64");
    if (!strcmp(path, "/dev/dma_heap/system") || !strcmp(path, "/dev/dma_heap/system-uncached"))
        flags &= ~3; /* O_ACCMODE: preserve CLOEXEC, use O_RDONLY. */
    return next(path, flags, mode);
}

int open(const char *path, int flags, ...) {
    va_list args;
    va_start(args, flags);
    mode_t mode = mode_argument(flags, args);
    va_end(args);
    int (*next)(const char *, int, ...) = (int (*)(const char *, int, ...))dlsym((void *)-1, "open");
    if (!strcmp(path, "/dev/dma_heap/system") || !strcmp(path, "/dev/dma_heap/system-uncached"))
        flags &= ~3;
    return next(path, flags, mode);
}
