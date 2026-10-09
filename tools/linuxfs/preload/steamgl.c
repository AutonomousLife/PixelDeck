/* Steam's native compositor requests GL 4.3, although its drawing works on
 * PanVK/Zink's real GL 3.3 context. Enabled only for verified driver imports. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static bool steam_gl;

__attribute__((constructor)) static void steam_gl_init(void)
{
   const char *enabled = getenv("BL_PANVK_STEAM_GL");
   char executable[4096];
   if (!enabled || strcmp(enabled, "1"))
      return;
   ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
   if (length < 0)
      return;
   executable[length] = '\0';
   const char *name = strrchr(executable, '/');
   steam_gl = name && !strcmp(name + 1, "steamwebhelper");
   if (steam_gl) {
      unsetenv("LIBGL_KOPPER_DISABLE");
      /* Native Gamescope presents bypass Xwayland's MSC, which stays stale.
       * Withdraw that timing capability so CEF uses the real RandR refresh. */
      const char *dmabuf = getenv("PANVK_KBASE_WAYLAND_DMABUF");
      if (dmabuf && !strcmp(dmabuf, "1"))
         setenv("glx_extension_override", "-GLX_OML_sync_control", 0);
   }
}

void *pixel_steam_SDL_GL_CreateContext(void *window)
{
   /* Resolve the actual SDL3 object: RTLD_NEXT can miss its local dlopen scope.
    * The versioned export leaves SDL2's incompatible ABI untouched. */
   void *sdl = dlopen("libSDL3.so.0", RTLD_NOW | RTLD_NOLOAD);
   void *(*create)(void *) = sdl ? dlvsym(sdl, "SDL_GL_CreateContext", "SDL3_0.0.0") : NULL;
   if (!create)
      return NULL;
   if (steam_gl) {
      bool (*get)(int, int *) = dlvsym(sdl, "SDL_GL_GetAttribute", "SDL3_0.0.0");
      bool (*set)(int, int) = dlvsym(sdl, "SDL_GL_SetAttribute", "SDL3_0.0.0");
      int major, minor, profile;
      if (get && set && get(17, &major) && get(18, &minor) && get(20, &profile) &&
          major == 4 && minor == 3 && profile == 1)
         set(17, 3);
   }
   void *context = create(window);
   dlclose(sdl);
   return context;
}
__asm__(".symver pixel_steam_SDL_GL_CreateContext, SDL_GL_CreateContext@SDL3_0.0.0");
