# -*- coding: utf-8 -*-
"""易盾滑块求解子模块(纯协议, 无浏览器)

主要接口:
  from logic.zhihuishu.yidun import yidun_solver
  solver = yidun_solver.YidunSolver(session, log_func)
  validate = solver.solve()   # -> "CN31_xxx_v_i_1" 或 None
"""
from logic.zhihuishu.yidun import yidun_js  # noqa: F401
from logic.zhihuishu.yidun.yidun_solver import YidunSolver, YidunSolveError  # noqa: F401

__all__ = ["yidun_js", "YidunSolver", "YidunSolveError"]
