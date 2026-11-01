# -*- coding: utf-8 -*-
"""多任务点并发 专项自测(离线, 不触网/不需真实账号)

运行:
    python tests\\test_mtp_concurrency.py
    (或) set PYTHONPATH=<yatori-python-console> && python tests\\test_mtp_concurrency.py
退出码: 0=全绿 / 1=有失败

覆盖:
  T1 并发参数计算(parallel.py): 下限/全速单调/节点间隔范围
  T2 停止标志: request_stop/clear_stop/is_stopped + 账号隔离
  T3 登录池建池(_user_block, videoModel=3):
     · cxNode=N → 池大小=N, 队列=N, 预登录=N
     · 停止再启动(重复建池) → 队列/池不累积(修复点)
     · cxNode=-1(无限制) → 不预登录, 池为空
     · cxNode=0(未配置) → 默认 3 并发
  T4 池调度互斥(复刻 _chapter_study 的取还/配额语义):
     · 同一 session 不被两个任务点同时持有
     · 同时持有 session 数 <= 池大小
     · 活跃课程计数进出配对(最终归零; 修复点)
  T5 _record_node_login 并发计数(线程安全)
  T6 源码不变量: 归还/释放阻塞取/flush/计数位置
"""
import functools
import inspect
import os
import queue as _q
import sys
import threading
import time
import types

print = functools.partial(print, flush=True)
# tests/ 的上一级即工程根(yatori-python-console)
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
ok = fail = 0


def chk(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[OK] {name} {extra}")
    else:
        fail += 1
        print(f"[FAIL] {name} {extra}")


# ===================== T1 并发参数 =====================
print("=" * 70)
print("T1 parallel 并发参数")
from logic.core import parallel as par  # noqa: E402

chk("work_concurrency>=2", par.work_concurrency() >= 2,
    par.work_concurrency())
chk("login_workers>=8", par.login_workers() >= 8, par.login_workers())
chk("fast_video_workers>=5", par.fast_video_workers() >= 5,
    par.fast_video_workers())
chk("ai_concurrency>=1", par.ai_concurrency() >= 1, par.ai_concurrency())
chk("tuned_work>=1", par.tuned_work_concurrency() >= 1,
    par.tuned_work_concurrency())
chk("tuned_video>=3", par.tuned_fast_video_workers() >= 3,
    par.tuned_fast_video_workers())
_itv = par.node_start_interval()
chk("节点间隔 0.06~2.0", 0.06 <= _itv <= 2.0, _itv)

_old = os.environ.get("YATORI_FULL_CPU")
os.environ["YATORI_FULL_CPU"] = "0"
_w_def = par.work_concurrency()
os.environ["YATORI_FULL_CPU"] = "1"
_w_full = par.work_concurrency()
if _old is None:
    os.environ.pop("YATORI_FULL_CPU", None)
else:
    os.environ["YATORI_FULL_CPU"] = _old
chk("全速并发>=默认并发", _w_full >= _w_def, f"default={_w_def} full={_w_full}")
chk("非1核串行化(>1)", _w_def > 1, _w_def)


# ===================== 公共 mock =====================
from logic.xuexitong import part as P  # noqa: E402
from config.config import User, Setting, CoursesCustom  # noqa: E402

_SAVED = {}


def _patch():
    names = ["_pull_course_action", "_jf_scan_and_daily_policy",
             "_rest_wait_if_needed", "_exam_guard_due_consume",
             "_exam_guard_action", "_jf_final_report",
             "send_user_event_notice", "generic_user_block", "log_print"]
    for n in names:
        if hasattr(P, n):
            _SAVED[n] = getattr(P, n)
    P._pull_course_action = lambda cache: []
    P._jf_scan_and_daily_policy = lambda *a, **k: None
    P._rest_wait_if_needed = lambda *a, **k: False
    P._exam_guard_due_consume = lambda *a, **k: None
    P._exam_guard_action = lambda *a, **k: None
    P._jf_final_report = lambda *a, **k: None
    P.send_user_event_notice = lambda *a, **k: None
    P.generic_user_block = lambda *a, **k: None
    P.log_print = lambda *a, **k: None
    try:
        import utils.sponsor as _sp
        _SAVED["__sponsor__"] = getattr(_sp, "print_sponsor_banner", None)
        _sp.print_sponsor_banner = lambda *a, **k: None
    except Exception:
        pass
    _SAVED["__relogin__"] = P.xxt_api.relogin


def _restore():
    for n, v in _SAVED.items():
        if n == "__sponsor__":
            try:
                import utils.sponsor as _sp
                _sp.print_sponsor_banner = v
            except Exception:
                pass
        elif n == "__relogin__":
            P.xxt_api.relogin = v
        else:
            setattr(P, n, v)
    _SAVED.clear()


ACC = "13800000000"


def run_block(cx_node, reset=False, video_model=3):
    calls = {"relogin": 0}

    def _rel(c):
        calls["relogin"] += 1
        return None
    P.xxt_api.relogin = _rel
    if reset:
        P._model3_caches.pop(ACC, None)
        P._model3_pool_queues.pop(ACC, None)
        P._account_login_counts.pop(ACC, None)
    u = User(account_type="XUEXITONG", account=ACC, password="p",
             courses_custom=CoursesCustom(video_model=video_model,
                                          cx_node=cx_node))
    s = Setting()
    c = types.SimpleNamespace(account=ACC)
    P.clear_stop(ACC)
    P._user_block(s, u, c)
    return calls


# ===================== T2 停止标志 =====================
print("=" * 70)
print("T2 停止标志")
P.clear_stop("acc-stop")
chk("T2-1 初始未停止", not P.is_stopped("acc-stop"))
P.request_stop("acc-stop")
chk("T2-2 置位后已停止", P.is_stopped("acc-stop"))
chk("T2-3 账号隔离", not P.is_stopped("acc-other"))
P.clear_stop("acc-stop")
chk("T2-4 清除后恢复", not P.is_stopped("acc-stop"))

# ===================== T3 登录池建池 =====================
print("=" * 70)
print("T3 登录池建池 (videoModel=3)")
_patch()
try:
    c1 = run_block(3, reset=True)
    chk("T3-1 池大小=cxNode(3)", len(P._model3_caches[ACC]) == 3,
        len(P._model3_caches[ACC]))
    chk("T3-2 队列 qsize=3",
        P._model3_pool_queues[ACC].qsize() == 3,
        P._model3_pool_queues[ACC].qsize())
    chk("T3-3 预登录=3次", c1["relogin"] == 3, c1)

    c2 = run_block(3, reset=False)   # 模拟"停止→再启动"
    chk("T3-4 重复建池队列不累积(=3)",
        P._model3_pool_queues[ACC].qsize() == 3,
        P._model3_pool_queues[ACC].qsize())
    chk("T3-5 重复建池池大小不累积(=3)",
        len(P._model3_caches[ACC]) == 3, len(P._model3_caches[ACC]))

    c3 = run_block(-1, reset=True)
    chk("T3-6 无限制模式不预登录", c3["relogin"] == 0, c3)
    chk("T3-7 无限制模式池为空", len(P._model3_caches[ACC]) == 0,
        len(P._model3_caches[ACC]))

    c4 = run_block(0, reset=True)
    chk("T3-8 cxNode=0 默认3并发", len(P._model3_caches[ACC]) == 3, c4)
finally:
    _patch()  # 确保 mock 维持到后续用例

# ===================== T4 池调度互斥(复刻真实语义) =====================
print("=" * 70)
print("T4 池调度互斥 + 活跃课程计数配对")
POOL_N = 3
COURSES = 2
NODES = 5
pool = list(range(POOL_N))
q = _q.Queue()
for i in pool:
    q.put(i)
held = {}
lk = threading.Lock()
viol = [0]
cur = [0]
maxc = [0]
done = [0]
T4ACC = "t4-acc"
with P._active_course_guard:
    P._active_course_count[T4ACC] = 0


def _course(cid):
    # 真实语义: 进入课程 → active+1 → sem 容量 = len(pool)//active_n
    with P._active_course_guard:
        P._active_course_count[T4ACC] += 1
        active_n = P._active_course_count[T4ACC]
    sem = threading.BoundedSemaphore(max(1, POOL_N // max(active_n, 1)))
    ths = []
    for nid in range(NODES):
        sem.acquire()          # 课程级公平配额
        si = q.get()           # 阻塞取空闲 session

        def _node(si=si):
            try:
                with lk:
                    if held.get(si, 0) > 0:
                        viol[0] += 1
                    held[si] = held.get(si, 0) + 1
                    cur[0] += 1
                    maxc[0] = max(maxc[0], cur[0])
                time.sleep(0.004)
                with lk:
                    held[si] -= 1
                    cur[0] -= 1
                    done[0] += 1
            finally:
                q.put(si)      # 归还 - 对齐 pool_q.put(si)
                sem.release()
        t = threading.Thread(target=_node, daemon=True)
        ths.append(t)
        t.start()
    # 真实语义: 节点全部起完后立即递减(对齐 _chapter_study 末尾)
    with P._active_course_guard:
        P._active_course_count[T4ACC] = max(
            0, P._active_course_count[T4ACC] - 1)
    for t in ths:
        t.join()


cws = [threading.Thread(target=_course, args=(c,)) for c in range(COURSES)]
for t in cws:
    t.start()
for t in cws:
    t.join()

chk("T4-1 同 session 无双重持有", viol[0] == 0, f"violations={viol[0]}")
chk("T4-2 并发占用<=池大小", maxc[0] <= POOL_N, f"max={maxc[0]}")
chk("T4-3 全部节点完成", done[0] == COURSES * NODES,
    f"done={done[0]}/{COURSES * NODES}")
chk("T4-4 session 全部归还", q.qsize() == POOL_N, f"qsize={q.qsize()}")
with P._active_course_guard:
    _left = P._active_course_count.get(T4ACC, -1)
chk("T4-5 活跃课程计数归零", _left == 0, f"left={_left}")

# ===================== T5 并发登录计数 =====================
print("=" * 70)
print("T5 _record_node_login 并发计数")
T5ACC = "t5-acc"
P._account_login_counts.pop(T5ACC, None)


def _hit():
    for _ in range(20):
        P._record_node_login(T5ACC, True)


ts = [threading.Thread(target=_hit) for _ in range(10)]
for t in ts:
    t.start()
for t in ts:
    t.join()
chk("T5-1 并发计数=200(线程安全)",
    P._account_login_counts.get(T5ACC) == 200,
    P._account_login_counts.get(T5ACC))

# ===================== T6 源码不变量 =====================
print("=" * 70)
print("T6 源码不变量")
_src_course = inspect.getsource(P._chapter_study)
chk("T6-1 节点用完归还 pool_q.put(si)", "pool_q.put(si)" in _src_course)
chk("T6-2 course_sem.release()", "course_sem.release()" in _src_course)
chk("T6-3 阻塞取空闲 session pool_q.get()", "pool_q.get()" in _src_course)
chk("T6-4 有停止检查点", "is_stopped(" in _src_course)
_src_ub = inspect.getsource(P._user_block)
chk("T6-5 建池前 flush 队列(get_nowait)", "get_nowait" in _src_ub)
_idx_ifpool = _src_course.find("if pool:")
_idx_cnt = _src_course.find("_active_course_count[cache.account] = (")
chk("T6-6 活跃计数位于 if pool 之内(修复泄漏)", 0 <= _idx_ifpool < _idx_cnt,
    f"if_pool={_idx_ifpool} cnt={_idx_cnt}")

_restore()
print("=" * 70)
print(f"RESULT: OK={ok} FAIL={fail}")
sys.exit(0 if fail == 0 else 1)
