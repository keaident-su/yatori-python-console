# -*- coding: utf-8 -*-
"""tsjy(超星通识教育/学习广场)平台学习模块 — v2.0.4-beta1

背景: 学习通账号中存在 tsjy.chaoxing.com 平台的课程("学习广场"类),
其 URL 形如 https://tsjy.chaoxing.com/plaza/app?courseId=X&personId=Y&classId=Z&userId=W。
在标准的 gas/clazz 章节接口下这些课的"知识节点=0"(被跳过), 需要走独立学习链路。

逆向成果(2026-09-30, 全部实测通过):
1. 鉴权: /plaza/ API 必须带 Referer=tsjy.chaoxing.com/plaza/app?courseId={cid}
2. 节点: GET /plaza/course/{cid}/node-list?page=N
   → {total,pages,list:[{nodeId,name,desc,video,exercises,finishStatus,...}]}
3. 打开: GET /plaza/user/{cid}/{nodeId}/modify-node → {mode,domain,h5enc}
4. 学习页: GET {domain}/mooc-ans/knowledge/cards?clazzid=0&courseid={cid}
   &knowledgeid={nodeId}&num=0&isPhone=1&h5enc={h5enc}&cpi=
   → HTML 内 AttachmentSetting JSON(取 aid/objectId/jobid/mtEnc/fid/userid/cpi)
5. 上报: POST mooc1-1.chaoxing.com/keeper/api/receive-studylog
   form: log=URL编码(JSON), enc=mtEnc原值
   log={"courseId":cid,"clazzId":0,"personId":cpi,"eventType":4,"eventTime":ms,
        "data":{"relationId":aid,"objectId":objectId,"fid":fid,"userId":userid,
                "jobId":jobid,"knowledgeId":nodeId}}
   → {"status":true}  (eventType=4 为学习上报; 2 是人脸采集专用)

注: 仅 plaza 已注册(有节点)的课可刷; "课程不存在"的课为平台侧空课(学生端亦无任务)。
"""
import json
import re
import time
from typing import Any, Callable, List, Optional

from utils.log import (
    log_print, INFO, DEBUG, Green, Yellow, Red, Blue, Purple, Default,
)

TSJY_HOST = "https://tsjy.chaoxing.com"
MOOC1_1 = "https://mooc1-1.chaoxing.com"

# 每节点上报次数(普通节点 2 次足够撑起"已学习"状态; 节点越多越慢, 保守取值)
_REPORT_PER_NODE = 2


class TsjyStudy:
    """tsjy 平台单账号学习器

    :param cache: 登录后的 XueXiTUserCache(cookie 必需)
    :param display: 日志显示的账号名(display_account 结果)
    :param stop_fn: 停止检查回调(返回 True 立即中止)
    """

    def __init__(self, cache: Any, display: str = "",
                 stop_fn: Optional[Callable[[], bool]] = None):
        from logic.xuexitong.api import _build_client, _do_get, _do_post_form
        self._do_get = _do_get
        self._do_post_form = _do_post_form
        self.client = _build_client(cache)
        self.display = display or getattr(cache, "account", "")
        self.stop_fn = stop_fn or (lambda: False)

    # ---------- 内部工具 ----------

    def _ref(self, cid: str, clz: str = "") -> str:
        """tsjy /plaza/ API 的 Referer(鉴权关键)"""
        ref = f"{TSJY_HOST}/plaza/app?courseId={cid}"
        if clz:
            ref += f"&classId={clz}"
        return ref

    def _log(self, course_name: str, level: str, *args):
        log_print(level, "[学习通]", "[", Green, self.display, Default, "] ",
                  "[", course_name, "] ", *args)

    def _stopped(self) -> bool:
        try:
            return bool(self.stop_fn())
        except Exception:
            return False

    @staticmethod
    def _parse_json(body: str) -> Any:
        try:
            return json.loads(body or "")
        except (json.JSONDecodeError, TypeError):
            return None

    # ---------- 链路步骤 ----------

    def list_nodes(self, cid: str, class_id: str = "",
                   page_max: int = 40) -> List[dict]:
        """拉取全部知识节点(自动翻页)"""
        nodes: List[dict] = []
        for pg in range(1, page_max + 1):
            url = f"{TSJY_HOST}/plaza/course/{cid}/node-list?page={pg}"
            if class_id:
                url += f"&classId={class_id}"
            body, _ = self._do_get(self.client, url,
                                   headers={"Referer": self._ref(
                                       cid, class_id)},
                                   retry=3)
            d = self._parse_json(body)
            if not isinstance(d, dict):
                break
            data = d.get("data") or {}
            lst = data.get("list") or []
            if not lst:
                break
            nodes.extend(lst)
            pages = data.get("pages") or 1
            if pg >= int(pages):
                break
        return nodes

    def open_node(self, cid: str, node_id: Any,
                  class_id: str = "") -> Optional[dict]:
        """打开节点: modify-node 拿 h5enc → 学习页解析 AttachmentSetting"""
        url = f"{TSJY_HOST}/plaza/user/{cid}/{node_id}/modify-node"
        if class_id:
            url += f"?classId={class_id}"
        body, _ = self._do_get(self.client, url,
                               headers={"Referer": self._ref(cid, class_id)},
                               retry=3)
        d = self._parse_json(body)
        h5enc = ((d or {}).get("data") or {}).get("h5enc", "")
        if not h5enc:
            return None
        cards = (f"{MOOC1_1}/mooc-ans/knowledge/cards?clazzid=0&courseid={cid}"
                 f"&knowledgeid={node_id}&num=0&isPhone=1&h5enc={h5enc}&cpi=")
        html, _ = self._do_get(self.client, cards,
                               headers={"Referer": self._ref(cid, class_id)},
                               retry=3)
        m = re.search(r"AttachmentSetting\s*=\s*(\{.*?\});", html or "", re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

    def report(self, cid: str, att_setting: dict, node_id: Any,
               clazz_id: str = "0") -> bool:
        """上报一次学习事件(eventType=4); 返回是否成功"""
        atts = att_setting.get("attachments") or []
        if not atts:
            return False
        defaults = att_setting.get("defaults") or {}
        mt = defaults.get("mtEnc", "")
        if not mt:
            return False
        ok = False
        for att in atts:
            data = {
                "relationId": att.get("aid", 0),
                "objectId": att.get("objectId", ""),
                "fid": defaults.get("fid", ""),
                "userId": defaults.get("userid", ""),
                "jobId": att.get("jobid", ""),
                "knowledgeId": int(node_id) if str(node_id).isdigit() else node_id,
            }
            log_obj = {"courseId": cid, "clazzId": int(clazz_id or 0),
                       "personId": defaults.get("cpi", ""), "eventType": 4,
                       "eventTime": int(time.time() * 1000), "data": data}
            body = ("log=" + _quote(json.dumps(log_obj, separators=(",", ":")))
                    + "&enc=" + mt)
            resp, _ = self._do_post_form(
                self.client,
                f"{MOOC1_1}/keeper/api/receive-studylog",
                body.encode("utf-8"),
                headers={"Referer": f"{MOOC1_1}/",
                         "Content-Type": "application/x-www-form-urlencoded"},
                retry=2)
            if '"status":true' in (resp or "").replace(" ", ""):
                ok = True
        return ok

    # ---------- 主流程 ----------

    def get_day_score(self, cid: str, class_id: str = "",
                      user_id: str = "") -> Optional[dict]:
        """查询课程每日积分(tsjy 积分系统, 2026-09-30 对齐参考实现 day-score)

        GET /plaza/score/{cid}/day-score?classId=&userId=
        → {totalScore, dayScore, itemDayScore:[{scoreType,score}], ...}
        积分来源: 看视频/阅读/测评等学习行为自动积累(学习广场课的游戏化机制)
        """
        url = (f"{TSJY_HOST}/plaza/score/{cid}/day-score"
               f"?classId={class_id}&userId={user_id}")
        try:
            body, _ = self._do_get(self.client, url,
                                   headers={"Referer": self._ref(
                                       cid, class_id)},
                                   retry=2)
            d = self._parse_json(body)
            if isinstance(d, dict) and d.get("success"):
                return d.get("data") or {}
        except Exception:
            pass
        return None

    def study_course(self, course: Any) -> bool:
        """学习一门 tsjy 课程: 遍历节点, 未完成节点逐个上报

        :param course: XueXiTCourse(course_id/course_name/key=classId/is_tsjy)
        :return: 是否至少完成一个节点的上报(或课程全部已完成时返回 True)
        """
        cid = str(getattr(course, "course_id", "") or "")
        clz = str(getattr(course, "key", "") or "")
        name = str(getattr(course, "course_name", "") or "")
        if not cid:
            return False
        try:
            nodes = self.list_nodes(cid, clz)
        except Exception as e:
            self._log(name, Red, f"节点拉取异常: {type(e).__name__}: {e}")
            return False
        if not nodes:
            self._log(name, Yellow,
                      "无知识节点(该课可能未在 tsjy 侧注册/为空课), 跳过")
            return False
        todo = [n for n in nodes if not n.get("finishStatus")]
        if not todo:
            self._log(name, Green, f"全部节点已完成({len(nodes)}个), 跳过")
            return True
        self._log(name, Blue,
                  f"节点总数 {len(nodes)}, 未完成 {len(todo)}, 开始学习")
        done = 0
        for i, n in enumerate(todo, 1):
            if self._stopped():
                self._log(name, Yellow, "检测到停止信号, 中止学习")
                break
            nid = n.get("nodeId")
            nname = str(n.get("name", ""))[:30]
            try:
                att = self.open_node(cid, nid, clz)
            except Exception:
                att = None
            if not att:
                self._log(name, Yellow,
                          f"  [{i}/{len(todo)}] {nname} 附件解析失败, 跳过")
                time.sleep(0.5)
                continue
            ok = False
            for _ in range(_REPORT_PER_NODE):
                try:
                    ok = self.report(cid, att, nid, clz) or ok
                except Exception:
                    pass
                time.sleep(1.5)
                if self._stopped():
                    break
            if ok:
                done += 1
                self._log(name, Green, f"  [{i}/{len(todo)}] {nname} 上报成功")
            else:
                self._log(name, Yellow, f"  [{i}/{len(todo)}] {nname} 上报失败")
            time.sleep(1.0)
        self._log(name, Purple,
                  f"tsjy 课程学习完毕: 完成上报 {done}/{len(todo)} 个节点")
        # 积分查询(学习广场课的游戏化积分, 学习行为自动累积)
        try:
            _uid = ""
            try:
                _uid = self.client.cookies.get("_uid") or ""
            except Exception:
                _uid = ""
            score = self.get_day_score(cid, clz, _uid)
            if score:
                self._log(name, Green,
                          f"课程积分: 累计 {score.get('totalScore', '?')}, "
                          f"今日 {score.get('dayScore', '?')}")
        except Exception:
            pass
        return done > 0 or not todo


def _quote(s: str) -> str:
    """URL 编码(等价 urllib.parse.quote + safe='')"""
    from urllib.parse import quote
    return quote(s, safe="")
