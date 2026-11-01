# -*- coding: utf-8 -*-
"""人类化节奏引擎 (2026-10-13, 用户定夺 A+B+C+D 全量)

针对"真随机/均匀分布=非人类特征"被识别的风险：
A 人类化分布+自相关: 对数正态分布(非均匀); 相邻题思考时间自相关
B 个体习惯模型: 每账号固定"行为基线程"(账号哈希决定, 长期稳定画像)
C 疲劳曲线+时段感知: 后半程变慢; 深夜/清晨降速
D 行为轨迹: 低概率"回看/改答案"(本模块只决策, 动作由调用方执行)

用法:
    from logic.xuexitong.human_pace import HumanPace
    pace = HumanPace(cache.account, mode=cc.cx_exam_pace)
    t = pace.think_time(idx, total)      # 单题思考秒数
    t = pace.read_time()                 # 开卷阅读秒数
    t = pace.pause()                     # 阶段长停秒数
    if pace.should_review(idx, total):   # D: 是否回看/改答案
        ...  # 调用方执行回看动作

mode: 0=旧行为(兼容, 均匀随机) / 1=标准人类化 / 2=谨慎(整体放慢)
"""
import hashlib
import math
import random
import time


class HumanPace:
    """按账号生成稳定"行为画像"的人类化节奏引擎"""

    def __init__(self, account: str, mode: int = 1):
        self.mode = int(mode or 1)
        try:
            self.mode = max(0, min(2, self.mode))
        except Exception:
            self.mode = 1
        # B: 个体基线程(账号哈希 -> 稳定随机源, 长期画像不变)
        h = hashlib.md5(str(account or "anon").encode("utf-8")).hexdigest()
        rnd = random.Random(int(h[:12], 16))
        self.base_read = rnd.uniform(4.0, 12.0)      # 开卷阅读基线(s)
        self.base_think = rnd.uniform(3.0, 8.0)      # 思考基线(s)
        self.style = rnd.uniform(0.65, 1.45)         # 快/慢风格系数
        self.wander = rnd.uniform(0.03, 0.15)        # 分心率(D概率加成)
        self.rng = random.Random()                   # 运行期随机
        self._prev_think = None
        # C: 时段感知(启动时快照)
        self.hour = time.localtime().tm_hour

    def _lognorm(self, mu: float, sigma: float) -> float:
        return self.rng.lognormvariate(math.log(max(mu, 0.5)), sigma)

    def think_time(self, idx: int = 0, total: int = 10) -> float:
        """单题思考时间(拉题->提交)"""
        if self.mode == 0:
            return self.rng.uniform(2.5, 7.0)        # 兼容旧行为
        t = self._lognorm(self.base_think * self.style, 0.45)
        # A: 自相关(与前题锚定50%, 概率60%: 快题后偏快/慢题后偏慢)
        if self._prev_think and self.rng.random() < 0.6:
            t = 0.5 * t + 0.5 * self._prev_think
        # C: 疲劳曲线(后半程至多+30%)
        if total > 1:
            prog = idx / (total - 1)
            t *= 1.0 + 0.30 * max(0.0, prog - 0.5) * 2.0
        # C: 深夜/清晨降速(+20%~+60%)
        hr = self.hour
        if hr >= 23 or hr < 6:
            t *= self.rng.uniform(1.2, 1.6)
        if self.mode == 2:
            t *= 1.4
        t = max(1.5, min(t, 180.0))
        self._prev_think = t
        return t

    def read_time(self) -> float:
        """开卷阅读时间(作业/章测进入前)"""
        if self.mode == 0:
            return self.rng.uniform(5.0, 15.0)
        t = self._lognorm(self.base_read, 0.4)
        if self.mode == 2:
            t *= 1.3
        return max(2.0, min(t, 120.0))

    def pause(self, scale: float = 3.0) -> float:
        """阶段长停顿(如答题中途停顿)"""
        if self.mode == 0:
            return self.rng.uniform(15.0, 45.0)
        t = self._lognorm(self.base_think * scale, 0.5)
        return max(5.0, min(t, 240.0))

    def should_review(self, idx: int = 0, total: int = 10) -> bool:
        """D: 是否执行"回看/改答案"(前期概率略高, 谨慎模式更低)"""
        if self.mode == 0:
            return False
        p = 0.09 if idx < max(1, int(total * 0.5)) else 0.04
        p *= (1.0 + self.wander)
        if self.mode == 2:
            p *= 0.7
        return self.rng.random() < p
