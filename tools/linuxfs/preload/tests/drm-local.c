/* Build twice: a fake local libdrm, then a caller of the globally preloaded shim. */
#ifdef DRM_TEST_LIBRARY
#include <stdint.h>
int drmIoctl(int fd, unsigned long request, void *arg) { return 123; }
int drmPrimeFDToHandle(int fd, int prime, uint32_t *handle) { *handle = 456; return 0; }
int drmPrimeHandleToFD(int fd, uint32_t handle, uint32_t flags, int *prime) { *prime = 789; return 0; }
int drmCloseBufferHandle(int fd, uint32_t handle) { return 321; }
#else
#include <assert.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
int main(void) {
  void *local = dlopen("libdrm.so.2", RTLD_NOW | RTLD_LOCAL);
  assert(local);
  int (*call)(int, unsigned long, void *) = dlsym(RTLD_DEFAULT, "drmIoctl");
  assert(call && call(-1, 0, NULL) == 123);
  int (*import)(int, int, uint32_t *) = dlsym(RTLD_DEFAULT, "drmPrimeFDToHandle");
  uint32_t handle = 0;
  assert(import && import(-1, -1, &handle) == 0 && handle == 456);
  int (*export)(int, uint32_t, uint32_t, int *) = dlsym(RTLD_DEFAULT, "drmPrimeHandleToFD");
  int prime = 0;
  assert(export && export(-1, handle, 0, &prime) == 0 && prime == 789);
  int (*close)(int, uint32_t) = dlsym(RTLD_DEFAULT, "drmCloseBufferHandle");
  assert(close && close(-1, handle) == 321);
  dlclose(local);
  puts("PASS local libdrm forwarding");
}
#endif
