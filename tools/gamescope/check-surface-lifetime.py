"""Apply the pinned patch and run actual lifetime/feedback bodies under ASan."""
from pathlib import Path
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-dir', type=Path, default=Path('build/panvk'))
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
expected = {
    'wlserver.cpp': 'f06ec27f40e0197e870bca86340267e64357ab36835f749aaf7246f3f809043d',
    'wlserver.hpp': 'f76acd3b3c25700e235864d56cca5373ef85198d9264624286ef18087416223f',
    'steamcompmgr.cpp': 'e32ccf49655bc40617777efb1d6d5441c3fe0e32704337c3df875da40ebde716',
    'commit.cpp': '99f6fb5e96cc5dcf486e5ff25c8f97be78a4c444835b2cf059e98e958f5a67ea',
    'commit.h': '29edafffd906dea41a5054c42b7e804404a3c22a41d3b59283389acdfe800999',
}

def function(source, name):
    start = source.index(name)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

def compiler_environment():
    if os.name != 'nt':
        return [shutil.which('clang++') or shutil.which('g++'), '-std=c++20',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g'], dict(os.environ)
    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
    install = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip()
    if not install:
        raise SystemExit('MSVC with AddressSanitizer is required on Windows')
    vcvars = Path(install)/'VC/Auxiliary/Build/vcvars64.bat'
    # Capture compiler setup privately; never print the environment.
    result = subprocess.check_output(f'cmd.exe /d /s /c ""{vcvars}" >nul && set"', text=True)
    env = {key.upper(): value for key, value in os.environ.items()}
    env.update((key.upper(), value) for key, value in (line.split('=', 1) for line in result.splitlines() if '=' in line and not line.startswith('=')))
    compiler = shutil.which('cl.exe', path=env['PATH'])
    assert compiler, 'vcvars64 did not provide cl.exe'
    return [compiler, '/nologo', '/std:c++20', '/EHsc', '/fsanitize=address', '/Zi', '/MD'], env

with tempfile.TemporaryDirectory(prefix='gamescope-surface-') as directory:
    tmp = Path(directory)
    originals = {}
    for name, digest in expected.items():
        source = args.source_dir/('gamescope-3.16.29-'+name)
        if not source.exists():
            source = args.source_dir/'src'/name
        data = source.read_bytes().replace(b'\r\n', b'\n')
        if digest:
            assert hashlib.sha256(data).hexdigest() == digest, 'Wrong pinned source: '+name
        originals[name] = data.decode('utf8')
        target = tmp/'src'/name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
    patch_tool = shutil.which('patch') or 'C:/Program Files/Git/usr/bin/patch.exe'
    for name in ['0116-refresh-reused-shm-buffers.patch', '0117-preserve-current-swapchain-override.patch',
                 '0119-retire-destroyed-surface-commits.patch']:
        subprocess.run([patch_tool, '-p1', '--batch', '--fuzz=0'], cwd=tmp,
            input=(root/'tools/gamescope/patches'/name).read_bytes(), check=True)
    sources = {name: (tmp/'src'/name).read_text(encoding='utf8') for name in expected}
    cpp, steam = sources['wlserver.cpp'], sources['steamcompmgr.cpp']
    registry = cpp[cpp.index('struct SurfaceLifetime\n'):cpp.index('ResListEntry_t PrepareCommit(')]
    prepare = function(cpp, 'ResListEntry_t PrepareCommit(')
    assert 'wlserver_surface_serial( surf )' in prepare
    assert 'commit->surface_serial = surface_serial;' in steam
    assert 'reslistentry.fifo,\n\t\treslistentry.surface_serial );' in steam
    assert steam.count('lastCommit->surface_serial,') == 2
    assert 'uint64_t surface_serial = 0;' in sources['commit.h']
    assert 'uint64_t surface_serial = 0;' in sources['wlserver.hpp']
    assert 'wlserver_presentation_feedback_discard(surf, surface_serial, presentation_feedbacks);' in sources['commit.cpp']
    for name in ['wlserver_presentation_feedback_presented', 'wlserver_presentation_feedback_discard', 'wlserver_past_present_timing']:
        body = function(cpp, 'void '+name+'(')
        assert body.index('wlserver_surface_is_alive') < body.index('get_wl_surface_info')
        declaration = next(line for line in sources['wlserver.hpp'].splitlines() if line.startswith('void '+name+'('))
        assert body[:body.index('\n{')]+';' == declaration
    destroy = function(cpp, 'static void handle_wl_surface_destroy(')
    assert destroy.index('serial = 0;') < destroy.index('wl_resource_destroy( feedback )') < destroy.index('delete surf;')
    update = function(steam, 'void update_wayland_res(')
    prelude = update[:update.index('\n\t// If we ever use HDR')]+ '\n}\n'
    assert prelude.index('wlserver_lock();') < prelude.index('wlserver_surface_is_alive') < prelude.index('reslistentry.surf->buffer_damage') < prelude.rindex('wlserver_unlock();')
    assert 'update_wayland_res( &g_steamcompmgr_xdg_done_commits, matched, tmp_queue[ i ] );' in steam
    # No source changes to the image completion or pacing paths.
    for name in ['handle_done_commit(', 'check_new_xwayland_res(']:
        assert function(steam, name) == function(originals['steamcompmgr.cpp'], name)

    prefix = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <list>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>
#include <ctime>
static bool locked;
bool wlserver_is_lock_held() { return locked; }
void wlserver_lock() { assert(!locked); locked=true; }
void wlserver_unlock() { assert(locked); locked=false; }
struct wl_list {};
struct wl_listener { wl_list link; void (*notify)(wl_listener *, void *)=nullptr; };
struct wl_resource;
struct wlr_surface { void *data; wl_resource *resource; struct { struct { int x1=0,y1=0,x2=32,y2=32; } extents; } buffer_damage; struct { int destroy,commit; } events; };
struct wl_resource { void *data=nullptr; void (*destroy)(wl_resource *)=nullptr; unsigned id=1; };
struct wl_client {};
struct wlr_buffer { int locks=1; };
struct wlserver_x11_surface_info { uint32_t wl_id,x11_id; wlr_surface *main_surface; void *xwayland_server; };
struct wlserver_vk_swapchain_feedback {};
namespace gamescope { struct CAcquireTimelinePoint {}; struct CReleaseTimelinePoint {}; }
struct ResListEntry_t {
wlr_surface *surf; wlr_buffer *buf; bool async=false,fifo=false;
std::shared_ptr<wlserver_vk_swapchain_feedback> feedback;
std::vector<wl_resource *> presentation_feedbacks;
std::optional<uint32_t> present_id; uint64_t desired_present_time=0;
std::shared_ptr<gamescope::CAcquireTimelinePoint> pAcquirePoint;
std::shared_ptr<gamescope::CReleaseTimelinePoint> pReleasePoint;
uint64_t surface_serial=0;
};
struct CommitDoneList_t {};
struct steamcompmgr_win_t { wlr_surface *override_surface() { return nullptr; } wlr_surface *current_surface() { return nullptr; } };
struct SyncSurface { void Detach() {} };
struct wlserver_wl_surface_info {
wlr_surface *wlr; wlserver_x11_surface_info *x11_surface=nullptr; void *xdg_surface=nullptr;
std::vector<wl_resource *> pending_presentation_feedbacks, gamescope_swapchains;
SyncSurface *pSyncobjSurface=nullptr; uint64_t sequence=0; wl_listener destroy,commit;
};
static std::list<ResListEntry_t> g_PendingCommits;
static wl_list pending_surfaces;
static struct { wlr_surface *mouse_focus_surface=nullptr,*kb_focus_surface=nullptr; std::unordered_map<wlr_surface *,int> current_dropdown_surfaces; } wlserver;
static struct { template<class... T> void errorf(const char *,T...) {} } xwm_log;
void wlserver_x11_surface_info_finish(wlserver_x11_surface_info *) {}
void wlserver_x11_surface_info_init(wlserver_x11_surface_info *,void *,int) {}
void wlserver_xdg_surface_info_finish(void *) {}
void wlserver_drag_anchor_forget(wlr_surface *) {}
void wlserver_x11_surface_info_set_wlr(wlserver_x11_surface_info *,wlr_surface *,bool) {}
void wl_list_remove(wl_list *) {}
void wl_signal_add(int *,wl_listener *) {}
void handle_wl_surface_commit(wl_listener *,void *) {}
void wlr_buffer_unlock(wlr_buffer *b) { assert(locked && b->locks==1); --b->locks; }
#define wl_container_of(ptr,sample,member) reinterpret_cast<wlserver_wl_surface_info *>(reinterpret_cast<char *>(ptr)-offsetof(wlserver_wl_surface_info,member))
#define wl_list_for_each_safe(s,tmp,head,member) for(s=nullptr; s; s=nullptr)
static std::set<wl_resource *> live_resources;
static unsigned resource_destroys, presented_events, discarded_events, timing_events;
wl_resource *wl_resource_create(wl_client *,void *,unsigned,uint32_t id) { auto *r=new wl_resource; r->id=id; live_resources.insert(r); return r; }
void wl_resource_set_implementation(wl_resource *r,void *,void *data,void (*cb)(wl_resource *)) { r->data=data; r->destroy=cb; }
void *wl_resource_get_user_data(wl_resource *r) { assert(live_resources.count(r)); return r->data; }
void wl_resource_set_user_data(wl_resource *r,void *data) { assert(live_resources.count(r)); r->data=data; }
unsigned wl_resource_get_version(wl_resource *) { return 1; }
uint32_t wl_resource_get_id(wl_resource *r) { return r->id; }
void wl_resource_post_no_memory(wl_resource *) { assert(false); }
void wl_resource_destroy(wl_resource *r) { assert(locked && live_resources.count(r)); if(r->destroy)r->destroy(r); live_resources.erase(r);++resource_destroys;delete r; }
wlr_surface *wlr_surface_from_resource(wl_resource *r) { return static_cast<wlr_surface *>(r->data); }
static int wp_presentation_feedback_interface;
void wp_presentation_feedback_send_discarded(wl_resource *r) { assert(live_resources.count(r)); ++discarded_events; }
template<class... T> void wp_presentation_feedback_send_presented(wl_resource *r,T...) { assert(live_resources.count(r)); ++presented_events; }
template<class... T> void gamescope_swapchain_send_past_present_timing(wl_resource *r,T...) { assert(live_resources.count(r)); ++timing_events; }
#define WP_PRESENTATION_FEEDBACK_KIND_VSYNC 1u
#define WP_PRESENTATION_FEEDBACK_KIND_HW_CLOCK 2u
#define WP_PRESENTATION_FEEDBACK_KIND_ZERO_COPY 4u
wlserver_wl_surface_info *get_wl_surface_info(wlr_surface *s) { return s ? static_cast<wlserver_wl_surface_info *>(s->data) : nullptr; }
struct commit_t {
std::mutex m_WaitableCommitStateMutex; void CloseFenceInternal() {}
void *vulkanTex=nullptr; wlr_surface *surf=nullptr; uint64_t surface_serial=0;
wlr_buffer *buf; std::vector<wl_resource *> presentation_feedbacks;
~commit_t();
};
'''
    bodies = [registry]
    for name in ['static void handle_wl_surface_destroy(', 'static void wlserver_new_surface(',
                 'static void presentation_time_feedback(', 'void wlserver_presentation_feedback_presented(',
                 'void wlserver_presentation_feedback_discard(', 'void wlserver_past_present_timing(']:
        bodies.append(function(cpp, name))
    bodies.append(prelude)
    bodies.append(function(sources['commit.cpp'], 'commit_t::~commit_t()'))
    bodies.append(function(originals['wlserver.cpp'], 'void wlserver_presentation_feedback_presented(').replace('void wlserver_presentation_feedback_presented(', 'void unsafe_original_presented(', 1))
    tests = r'''
static wlr_surface *create_surface() {
 assert(locked); auto *s=new wlr_surface{}; s->resource=new wl_resource{};
 wlserver_new_surface(nullptr,s); return s;
}
static void destroy_surface(wlr_surface *s,bool free_memory=true) {
 assert(locked); auto *info=get_wl_surface_info(s);
 handle_wl_surface_destroy(&info->destroy,nullptr);
 if(free_memory){ delete s->resource; delete s; }
}
static std::vector<wl_resource *> feedback(wlr_surface *s) {
 wl_resource surface_resource; surface_resource.data=s;
 wl_resource presentation_resource;
 presentation_time_feedback(nullptr,&presentation_resource,&surface_resource,42);
 auto *info=get_wl_surface_info(s); auto result=std::move(info->pending_presentation_feedbacks); info->pending_presentation_feedbacks.clear(); return result;
}
int main(int argc,char **) {
 wlserver_lock(); auto *s=create_surface(); auto serial=wlserver_surface_serial(s);
 auto resources=feedback(s);
 if(argc>1) {
  destroy_surface(s); unsafe_original_presented(s,resources,1,1); return 2;
 }
 assert(wlserver_surface_is_alive(s,serial));
 wlserver_presentation_feedback_presented(s,serial,resources,100,10);
 assert(resources.empty() && presented_events==1 && resource_destroys==1);
 resources=feedback(s);
 wlserver_presentation_feedback_discard(s,serial,resources);
 assert(resources.empty() && discarded_events==1 && resource_destroys==2);
 // Feedback can leave the pending list but remains owned until its surface dies.
 resources=feedback(s); auto stale=resources; wlr_buffer queue_buffer;
 ResListEntry_t queued{s,&queue_buffer}; queued.surface_serial=serial; queued.presentation_feedbacks=resources;
 destroy_surface(s);
 assert(discarded_events==2 && resource_destroys==3 && live_resources.empty());
 assert(!wlserver_surface_is_alive(s,serial));
 wlserver_presentation_feedback_presented(s,serial,resources,100,10);
 wlserver_past_present_timing(s,serial,1,0,0,0,0);
 assert(resources.empty() && presented_events==1 && timing_events==0);
 wlserver_presentation_feedback_discard(s,serial,stale);
 assert(stale.empty() && resource_destroys==3);
 wlserver_unlock(); update_wayland_res(nullptr,nullptr,queued);
 assert(!locked && queue_buffer.locks==0 && queued.presentation_feedbacks.empty());
 // Reuse the exact surface address; the old generation must not match.
 wlserver_lock(); auto *reused=create_surface(); auto old_serial=wlserver_surface_serial(reused);
 destroy_surface(reused,false); wlserver_new_surface(nullptr,reused);
 auto new_serial=wlserver_surface_serial(reused);
 assert(new_serial!=old_serial && !wlserver_surface_is_alive(reused,old_serial));
 assert(wlserver_surface_is_alive(reused,new_serial));
 auto new_resources=feedback(reused); auto new_sequence=get_wl_surface_info(reused)->sequence;
 std::vector<wl_resource *> old_resources;
 wlserver_presentation_feedback_presented(reused,old_serial,old_resources,0,0);
 assert(get_wl_surface_info(reused)->sequence==new_sequence && new_resources.size()==1);
 // Live unmatched queues discard once and release once too.
 wlr_buffer unmatched_buffer; ResListEntry_t unmatched{reused,&unmatched_buffer};
 unmatched.surface_serial=new_serial; unmatched.presentation_feedbacks=std::move(new_resources);
 wlserver_unlock(); update_wayland_res(nullptr,nullptr,unmatched);
 assert(!locked && unmatched_buffer.locks==0 && unmatched.presentation_feedbacks.empty());
 wlserver_lock(); auto *held_surface=create_surface(); auto held_serial=wlserver_surface_serial(held_surface);
 auto held_resources=feedback(held_surface); destroy_surface(held_surface); wlserver_unlock();
 wlr_buffer held_buffer;
 { commit_t held; held.surf=held_surface; held.surface_serial=held_serial; held.buf=&held_buffer; held.presentation_feedbacks=std::move(held_resources); }
 assert(!locked && held_buffer.locks==0 && live_resources.empty());
 wlserver_lock(); destroy_surface(reused);
 // Client cleanup can destroy a feedback resource before its surface callback.
 auto *closing=create_surface(); auto closing_feedback=feedback(closing);
 wl_resource_destroy(closing_feedback.front());
 assert(g_LiveSurfaces.at(closing).presentation_feedbacks.empty());
 destroy_surface(closing); // Must not destroy that resource for a second time.
 // The live present-id route still reaches the protocol resource.
 auto *timed=create_surface(); auto timed_serial=wlserver_surface_serial(timed);
 auto *swapchain=wl_resource_create(nullptr,nullptr,1,99);
 get_wl_surface_info(timed)->gamescope_swapchains.push_back(swapchain);
 wlserver_past_present_timing(timed,timed_serial,1,0,0,0,0);
 assert(timing_events==1);
 destroy_surface(timed); assert(swapchain->data==nullptr);
 wl_resource_destroy(swapchain); wlserver_unlock();
 assert(g_LiveSurfaces.empty());
 return 0;
}
'''
    unit = tmp/'lifetime.cpp'
    unit.write_text(prefix+'\n'.join(bodies)+tests, encoding='utf8')
    command, env = compiler_environment()
    binary = tmp/('lifetime.exe' if os.name=='nt' else 'lifetime')
    if os.name == 'nt':
        command += [str(unit), '/Fe:'+str(binary), '/Fo:'+str(tmp/'lifetime.obj'), '/Fd:'+str(tmp/'lifetime.pdb')]
    else:
        command += [str(unit), '-o', str(binary)]
    subprocess.run(command, cwd=tmp, env=env, check=True)
    subprocess.run([str(binary)], cwd=tmp, env=env, check=True)
    broken = subprocess.run([str(binary), '--original'], cwd=tmp, env=env, capture_output=True, text=True)
    assert broken.returncode != 0 and 'heap-use-after-free' in broken.stdout+broken.stderr, broken.stdout+broken.stderr
    print('PASS: exact-source patch + existing 0116/0117; actual function bodies compile/run under ASan; live/dead/reused surface, queued/held feedback and single buffer release; original function reproduces heap-use-after-free')
