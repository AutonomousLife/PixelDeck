"""Compile actual Gamescope association routines and reproduce lost destruction owners."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


HARNESS = r'''
#include <map>
#include <vector>
#include <cassert>
#include <cstdlib>
#include <cstdio>
struct wl_list {};
void wl_list_remove(wl_list*) {}
void wl_list_init(wl_list*) {}
struct wlserver_x11_surface_info;
struct wlserver_wl_surface_info { wlserver_x11_surface_info *x11_surface=nullptr; };
struct wlr_surface { wlserver_wl_surface_info info; };
struct ResListEntry_t { wlr_surface *surf; void *buf; };
std::vector<ResListEntry_t> g_PendingCommits;
void wlr_buffer_unlock(void*) {}
struct wlserver_content_override { wlr_surface *surface; unsigned x11_window; void *gamescope_swapchain; struct { wl_list link; } surface_destroy_listener; };
struct gamescope_xwayland_server_t {
 std::map<unsigned,wlserver_content_override*> content_overrides;
 void destroy_content_override(wlserver_content_override*);
 void wayland_commit(ResListEntry_t) {}
};
struct wlserver_x11_surface_info { wlr_surface *main_surface=nullptr,*override_surface=nullptr; gamescope_xwayland_server_t *xwayland_server=nullptr; wl_list pending_link; };
std::map<unsigned,wlserver_x11_surface_info*> windows;
wlserver_x11_surface_info *lookup_x11_surface_info_from_xid(gamescope_xwayland_server_t*,unsigned id) { return windows[id]; }
wlserver_wl_surface_info *get_wl_surface_info(wlr_surface *s) { assert(s);return &s->info; }
bool wlserver_is_lock_held() { return true; }
void gamescope_swapchain_send_retired(void*) {}
#define CHECK(x) do { if(!(x)) {std::fprintf(stderr,"failed line %d\n",__LINE__);std::exit(2);} } while(0)
ROUTINES
void retire(gamescope_xwayland_server_t &server,wlr_surface &surface) {
 auto *co=static_cast<wlserver_content_override*>(std::calloc(1,sizeof(wlserver_content_override)));
 co->surface=&surface;co->x11_window=1;server.content_overrides[1]=co;
 server.destroy_content_override(co);
}
int main() {
 gamescope_xwayland_server_t server;
 wlserver_x11_surface_info owner,other;owner.xwayland_server=other.xwayland_server=&server;windows[1]=&owner;
 wlr_surface a,b,c;
 wlserver_x11_surface_info_set_wlr(&owner,&a,false);
 wlserver_x11_surface_info_set_wlr(&owner,&a,true);
 retire(server,a);
 CHECK(!owner.override_surface && owner.main_surface==&a && a.info.x11_surface==&owner);
 wlserver_x11_surface_info_set_wlr(&owner,&b,true);
 retire(server,b);
 CHECK(!owner.override_surface && b.info.x11_surface==nullptr && a.info.x11_surface==&owner);
 wlserver_x11_surface_info_set_wlr(&owner,&a,true);
 wlserver_x11_surface_info_set_wlr(&owner,&b,true);
 CHECK(a.info.x11_surface==&owner && b.info.x11_surface==&owner);
 wlserver_x11_surface_info_set_wlr(&owner,&b,false);
 wlserver_x11_surface_info_set_wlr(&owner,&c,false);
 CHECK(b.info.x11_surface==&owner && c.info.x11_surface==&owner);
 wlserver_x11_surface_info_set_wlr(&other,&b,true);
 CHECK(!owner.override_surface && b.info.x11_surface==&other && other.override_surface==&b);
 retire(server,b);
 CHECK(b.info.x11_surface==&other && other.override_surface==&b);
 std::puts("Actual routines passed shared main/override retirement, replacement and owner transfer.");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--old-source', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('compiler_source', ROOT/'tools/pixel-probe/check-kcpu-fence-status.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cc, env = module.compiler()
    with tempfile.TemporaryDirectory(dir=ROOT/'build', prefix='x11-associations-') as directory:
        path = Path(directory)
        for source_path, expected in [(args.source, 0), (args.old_source, 2)]:
            source = source_path.read_text(encoding='utf-8')
            routines = function(source, 'void gamescope_xwayland_server_t::destroy_content_override( struct wlserver_content_override *co )')
            # Skip the earlier forward declaration.
            start = source.rindex('static void wlserver_x11_surface_info_set_wlr(')
            routines += '\n' + function(source[start:], 'static void wlserver_x11_surface_info_set_wlr(')
            cpp = path/'check.cpp'
            cpp.write_text(HARNESS.replace('ROUTINES', routines))
            exe = path/('check.exe' if module.os.name == 'nt' else 'check')
            flags = ['/Fe:'+str(exe)] if module.os.name == 'nt' else ['-o',str(exe)]
            result = subprocess.run([*cc,str(cpp),*flags],cwd=path,env=env,capture_output=True,text=True)
            if result.returncode:
                raise RuntimeError(result.stdout+result.stderr)
            result = subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            if result.returncode != expected:
                raise RuntimeError(result.stdout+result.stderr)
            print(result.stdout.strip() if not expected else 'Original association routines failed the regression as expected.')


if __name__ == '__main__':
    main()
