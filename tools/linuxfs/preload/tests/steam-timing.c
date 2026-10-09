/* Run the real Steam constructor with controlled executable identities. */
#define _GNU_SOURCE
#define readlink timing_test_readlink
#include "../steamgl.c"
#undef readlink
#include <assert.h>

static const char *test_executable = "/runtime/steamwebhelper";
ssize_t timing_test_readlink(const char *path, char *buffer, size_t length)
{
   assert(!strcmp(path, "/proc/self/exe"));
   size_t count = strlen(test_executable);
   if (count > length) count = length;
   memcpy(buffer, test_executable, count);
   return count;
}

static void reset(void)
{
   steam_gl = false;
   test_executable = "/runtime/steamwebhelper";
   setenv("BL_PANVK_STEAM_GL", "1", 1);
   setenv("LIBGL_KOPPER_DISABLE", "true", 1);
   unsetenv("PANVK_KBASE_WAYLAND_DMABUF");
   unsetenv("glx_extension_override");
}

int main(void)
{
   reset();
   setenv("PANVK_KBASE_WAYLAND_DMABUF", "1", 1);
   steam_gl_init();
   assert(steam_gl && !getenv("LIBGL_KOPPER_DISABLE"));
   assert(!strcmp(getenv("glx_extension_override"), "-GLX_OML_sync_control"));

   reset();
   steam_gl_init();
   assert(steam_gl && !getenv("glx_extension_override"));
   reset();
   setenv("PANVK_KBASE_WAYLAND_DMABUF", "0", 1);
   steam_gl_init();
   assert(!getenv("glx_extension_override"));

   reset();
   test_executable = "/runtime/gamescope";
   setenv("PANVK_KBASE_WAYLAND_DMABUF", "1", 1);
   steam_gl_init();
   assert(!steam_gl && getenv("LIBGL_KOPPER_DISABLE") && !getenv("glx_extension_override"));
   reset();
   setenv("BL_PANVK_STEAM_GL", "0", 1);
   setenv("PANVK_KBASE_WAYLAND_DMABUF", "1", 1);
   steam_gl_init();
   assert(!steam_gl && !getenv("glx_extension_override"));

   reset();
   setenv("PANVK_KBASE_WAYLAND_DMABUF", "1", 1);
   setenv("glx_extension_override", "user-choice", 1);
   steam_gl_init();
   assert(!strcmp(getenv("glx_extension_override"), "user-choice"));
   return 0;
}
