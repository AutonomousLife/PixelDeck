"""Exercise the actual experimental worker with real threads and blocked GPU completion."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
THREADS = r'''
#include <mutex>
#include <condition_variable>
#include <thread>
using mtx_t = std::mutex;
using cnd_t = std::condition_variable;
using thrd_t = std::thread;
enum { thrd_success=0, mtx_plain=0 };
int mtx_init(mtx_t*, int) { return 0; }
void mtx_destroy(mtx_t*) {}
void mtx_lock(mtx_t* m) { m->lock(); }
void mtx_unlock(mtx_t* m) { m->unlock(); }
int cnd_init(cnd_t*) { return 0; }
void cnd_destroy(cnd_t*) {}
void cnd_wait(cnd_t* c, mtx_t* m) {
  std::unique_lock<std::mutex> lock(*m, std::adopt_lock);
  c->wait(lock); lock.release();
}
void cnd_signal(cnd_t* c) { c->notify_one(); }
void cnd_broadcast(cnd_t* c) { c->notify_all(); }
int thrd_create(thrd_t* t, int (*fn)(void*), void* p) {
  *t=std::thread([=]{fn(p);}); return 0;
}
void thrd_join(thrd_t t, int*) { t.join(); }
'''
HARNESS = r'''
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <initializer_list>
using VkResult = int;
enum { VK_SUCCESS=0, VK_SUBOPTIMAL_KHR=1, VK_ERROR_DEVICE_LOST=-4 };
struct VkRectLayerKHR { int x,y; uint32_t width,height,layer; };
struct VkPresentRegionKHR { uint32_t rectangleCount; const VkRectLayerKHR* pRectangles; };
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"failed line %d\n",__LINE__); std::exit(2); } } while(0)
#include "worker.h"
struct Context {
  std::atomic<int> entered{0}, published{0}, finished{0};
  std::atomic<bool> release{false};
  bool fail_wait=false, fail_publish=false;
  int damage=0;
};
void until(std::atomic<int>& value, int expected) {
  auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
  while(value.load()!=expected) {
    CHECK(std::chrono::steady_clock::now()<deadline);
    std::this_thread::yield();
  }
}
VkResult prepare(void* data,uint32_t) {
  auto* c=static_cast<Context*>(data); c->entered++;
  while(!c->release.load()) std::this_thread::yield();
  return c->fail_wait?VK_ERROR_DEVICE_LOST:VK_SUCCESS;
}
VkResult publish(void* data,uint32_t,const VkPresentRegionKHR* region) {
  auto* c=static_cast<Context*>(data);
  CHECK(c->release.load());
  if(region) { CHECK(region->rectangleCount==1); c->damage=region->pRectangles[0].x; }
  c->published++;
  return c->fail_publish?VK_ERROR_DEVICE_LOST:VK_SUCCESS;
}
void finished(void* data,uint32_t) { static_cast<Context*>(data)->finished++; }
int main() {
  {
    Context c; wsi_deferred_worker w{};
    CHECK(wsi_deferred_init(&w,2,&c,prepare,publish,finished));
    VkRectLayerKHR rectangle{7,0,1,1,0}; VkPresentRegionKHR damage{1,&rectangle};
    CHECK(wsi_deferred_enqueue(&w,0,&damage)); until(c.entered,1);
    rectangle.x=99; CHECK(c.published==0);
    CHECK(wsi_deferred_enqueue(&w,1,nullptr));
    CHECK(wsi_deferred_enqueue(&w,2,nullptr));
    CHECK(!wsi_deferred_enqueue(&w,3,nullptr));
    std::atomic<bool> joined{false};
    std::thread stop([&]{wsi_deferred_finish(&w);joined=true;});
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    CHECK(!joined.load()); CHECK(c.published==0);
    c.release=true; stop.join();
    CHECK(joined && c.finished==3 && c.published==3 && c.damage==7);
    CHECK(!w.initialized && w.jobs==nullptr);
  }
  for(bool failing_wait:{true,false}) {
    Context c; c.fail_wait=failing_wait; c.fail_publish=!failing_wait;
    wsi_deferred_worker w{};
    CHECK(wsi_deferred_init(&w,2,&c,prepare,publish,finished));
    CHECK(wsi_deferred_enqueue(&w,0,nullptr)); until(c.entered,1);
    CHECK(wsi_deferred_enqueue(&w,1,nullptr)); c.release=true;
    until(c.finished,2);
    CHECK(wsi_deferred_error(&w)==VK_ERROR_DEVICE_LOST);
    CHECK(!wsi_deferred_enqueue(&w,2,nullptr));
    wsi_deferred_finish(&w);
    CHECK(c.entered==2 && c.published==(failing_wait?0:1));
  }
  std::puts("Worker passed delayed completion, copied damage, bounded queue, sticky errors and teardown drain.");
}
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--header',type=Path,default=ROOT/'build/panvk/deferred-present-candidate/src/vulkan/wsi/wsi_deferred_present.h')
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('compiler_source',ROOT/'tools/pixel-probe/check-kcpu-fence-status.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cc,env=module.compiler()
    if module.os.name!='nt': cc.append('-pthread')
    with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='deferred-worker-') as directory:
        path=Path(directory); (path/'c11').mkdir()
        (path/'c11/threads.h').write_text(THREADS)
        # C11 joins consume the handle; the C++ adapter must move its std::thread.
        header=args.header.read_text().replace('thrd_join(w->thread, NULL);','thrd_join(std::move(w->thread), NULL);')
        header=header.replace('struct wsi_deferred_worker *w = arg;',
                              'struct wsi_deferred_worker *w = static_cast<wsi_deferred_worker*>(arg);')
        header=header.replace('w->jobs = calloc(capacity, sizeof(*w->jobs));',
                              'w->jobs = static_cast<wsi_deferred_job*>(calloc(capacity, sizeof(*w->jobs)));')
        header=header.replace('job.rectangles = malloc(bytes);',
                              'job.rectangles = static_cast<VkRectLayerKHR*>(malloc(bytes));')
        header=header.replace('struct wsi_deferred_job job = {0};',
                              'struct wsi_deferred_job job = {};')
        (path/'worker.h').write_text(header)
        (path/'check.cpp').write_text(HARNESS)
        exe=path/('check.exe' if module.os.name=='nt' else 'check')
        flags=['/I'+str(path),'/Fe:'+str(exe)] if module.os.name=='nt' else ['-I'+str(path),'-o',str(exe)]
        result=subprocess.run([*cc,str(path/'check.cpp'),*flags],cwd=path,env=env,capture_output=True,text=True)
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        subprocess.run([str(exe)],check=True,timeout=10)
        # Prove the test detects an early publication, rather than only a runnable thread.
        broken=header.replace('VkResult result = w->prepare(w->data, job.image);',
                              'VkResult result = VK_SUCCESS;')
        if broken==header: raise RuntimeError('Worker preparation anchor changed')
        (path/'worker.h').write_text(broken)
        result=subprocess.run([*cc,str(path/'check.cpp'),*flags],cwd=path,env=env,capture_output=True,text=True)
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        result=subprocess.run([str(exe)],capture_output=True,timeout=10)
        if result.returncode!=2: raise RuntimeError('Early-publication negative control passed')
        print('Early-publication negative control failed as expected.')

if __name__=='__main__': main()
