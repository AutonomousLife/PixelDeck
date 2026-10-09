"""Exercise the real wait routine without any mutable CPU emission fields."""
import argparse
import importlib.util
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <cstdint>
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#define CHECK(c) do { if (!(c)) { std::fprintf(stderr,"failed line %d\n",__LINE__); std::_Exit(2); } } while(0)
#define MIN2(a,b) ((a)<(b)?(a):(b))
#define PANVK_DEBUG(x) debug
#define u_foreach_bit(i,mask) for (unsigned i=0;i<3;i++) if ((mask)&(1u<<i))
#define KBASE_SEQNO_LS_COPY_OFFSET 16
#define KBASE_SEQNO_STREAM_PROGRESS_OFFSET 24
#define CS_USER_IO_OUTPUT_CS_EXTRACT 0
#define CS_USER_IO_OUTPUT_CS_ACTIVE 8
#define KBASE_WAIT_TIMEOUT_NS 1000000000ull
using VkResult=int;
enum { VK_SUCCESS=0, VK_TIMEOUT=2 };
struct panvk_cs_sync64 { uint64_t seqno; uint32_t error,pad; uint64_t ls; uint32_t progress; };
struct panvk_subqueue { struct { void *user_io; uint64_t ringbuf_dev; } kbase; };
struct panvk_device { struct { void *dev; } kmod; };
struct panvk_gpu_queue { struct { struct { void *device; } base; } vk; panvk_subqueue subqueues[3]; };
static panvk_cs_sync64 test_cell;
static panvk_device device;
alignas(8) static unsigned char io[12288];
static bool debug;
static int cqs_return, event_calls, cqs_calls, kicks;
static int64_t fake_now;
static panvk_device *to_panvk_device(void *p) { return static_cast<panvk_device *>(p); }
static volatile panvk_cs_sync64 *kbase_subqueue_seqno_cell(panvk_gpu_queue *,uint32_t) { return &test_cell; }
static uint64_t kbase_subqueue_seqno_dev_addr(panvk_gpu_queue *,uint32_t) { return 64; }
static unsigned kbase_seqno_stride() { return sizeof(test_cell); }
static void kbase_cache_invalidate_range(const void *,unsigned) {}
static int64_t os_time_get_nano() { return fake_now; }
static void kbase_kmod_csf_queue_kick(void *,uint64_t) { kicks++; }
static void mesa_loge(const char *,...) {}
static void mesa_logd(const char *,...) {}
static int vk_queue_set_lost(void *,const char *,...) { return -4; }
static int kbase_kmod_csf_wait_cqs64(void *,uint64_t,uint64_t target,int64_t) {
   CHECK(target == 8); cqs_calls++;
   if (cqs_return > 0) test_cell.seqno=9;
   return cqs_return;
}
static int kbase_kmod_csf_wait_event(void *,int64_t) { event_calls++; test_cell.seqno=9; return 0; }
@FUNCTION@
static void reset(panvk_gpu_queue &q) {
   test_cell={}; fake_now=0; debug=false; cqs_return=-1; event_calls=cqs_calls=kicks=0;
   q.vk.base.device=&device;
   for(auto &s:q.subqueues) { s.kbase.user_io=io; s.kbase.ringbuf_dev=128; }
   *reinterpret_cast<uint64_t *>(io+8192)=UINT64_MAX;
   *reinterpret_cast<uint32_t *>(io+8200)=0;
}
int main() {
   panvk_gpu_queue q{};
   reset(q); CHECK(kbase_subqueue_wait_seqno(&q,0,9,1,0)==VK_TIMEOUT);
   CHECK(cqs_calls==0); // A drained firmware ring is insufficient.
   reset(q); test_cell.seqno=9; CHECK(kbase_subqueue_wait_seqno(&q,0,9,1,0)==VK_SUCCESS);
   reset(q); test_cell.error=7; CHECK(kbase_subqueue_wait_seqno(&q,0,9,1,UINT64_MAX)==-4);
   reset(q); CHECK(kbase_subqueue_wait_seqno(&q,0,9,1,UINT64_MAX)==VK_SUCCESS);
   CHECK(cqs_calls==1 && event_calls==1); // Failed CQS still waits the actual target.
   reset(q); cqs_return=1; CHECK(kbase_subqueue_wait_seqno(&q,0,9,1,UINT64_MAX)==VK_SUCCESS);
   CHECK(event_calls==0 && cqs_calls==1);
   reset(q); debug=true; test_cell.ls=9; CHECK(kbase_subqueue_wait_seqno(&q,0,9,1,0)==VK_SUCCESS);
   reset(q); test_cell.ls=9; CHECK(kbase_subqueue_wait_seqno(&q,0,9,1,0)==VK_TIMEOUT);
}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesa-root',type=Path,default=ROOT/'build/panvk/mesa-driver')
    args=parser.parse_args()
    relative=Path('src/panfrost/vulkan/csf/panvk_vX_gpu_queue.c')
    original=(args.mesa_root/relative).read_text(encoding='utf-8')
    calls=re.findall(r'kbase_subqueue_wait_seqno\(\s*queue,.*?\);',original,re.S)
    assert len(calls)==5 and all('false,' in c for c in calls), 'Re-audit ring-drain users'
    candidate=ROOT/'build/panvk/concurrent-fence-wait-prerequisite'
    target=candidate/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(original,encoding='utf-8')
    subprocess.run(['git','apply','--unsafe-paths','--directory='+str(candidate),
                    str(ROOT/'tools/pixel-probe/panvk-concurrent-fence-wait.patch')],cwd=ROOT,check=True,capture_output=True)
    source=target.read_text(encoding='utf-8')
    function=re.search(r'static VkResult\nkbase_subqueue_wait_seqno\([^;{}]*\n\{.*?\n}\n',source,re.S).group()
    assert 'allow_ring_drain' not in source and 'target_insert' not in source
    assert 'last_job' not in function and 'ringbuf_cpu' not in function
    assert 'kbase_log_subqueue_state' not in function
    assert len(re.findall(r'kbase_subqueue_wait_seqno\(\s*queue,.*?\);',source,re.S))==5
    spec=importlib.util.spec_from_file_location('status_checker',ROOT/'tools/pixel-probe/check-kcpu-fence-status.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cc,env=module.compiler()
    cc=[f.replace('c++17','c++20') for f in cc]
    for name,body,passes in [('wait',function,True),('ring-drain-control',function.replace('if (cell->seqno >= target_seqno ||','if (extract == UINT64_MAX || cell->seqno >= target_seqno ||'),False)]:
        cpp=candidate/(name+'.cpp');cpp.write_text(HARNESS.replace('@FUNCTION@',body),encoding='utf-8')
        exe=candidate/(name+('.exe' if module.os.name=='nt' else ''))
        flags=['/Fe:'+str(exe)] if module.os.name=='nt' else ['-o',str(exe)]
        built=subprocess.run([*cc,str(cpp),*flags],cwd=candidate,env=env,capture_output=True,text=True)
        assert built.returncode==0,built.stdout+built.stderr
        ran=subprocess.run([str(exe)],cwd=candidate,capture_output=True)
        assert (ran.returncode==0)==passes,name
    print('Real wait routine passed: no mutable emission fields; actual seqno/error/fallback; ring-drain negative control failed.')


if __name__=='__main__':
    main()
