/* Deliberately broken diagnostic probe: run only to verify ASan and log collection. */
#include <stdlib.h>
static __attribute__((noinline)) int read_released(volatile int *pointer) { return *pointer; }
int main(void) {
    int *pointer = malloc(sizeof(*pointer));
    if (!pointer) return 2;
    *pointer = 42;
    free(pointer);
    return read_released(pointer);
}
