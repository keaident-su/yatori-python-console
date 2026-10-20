# -*- coding: utf-8 -*-
"""AI智课(mapCourse)协议客户端 (2026-10-14 完全破译版)

## 平台
    https://ai-smart-course-student-pro.zhihuishu.com  (mapCourse/AI智课)

## 加密体系 (完整闭环, 已实测验证)
    1) 密钥获取 labc(id):
       uid = RSA_PKCS1v15_encrypt(服务端公钥, {"module": id})
       -> GET https://appcomm-user.zhihuishu.com/app-commserv-user/c/has?uid=<密文>
       -> 响应 rt.sl  (172字符base64)
    2) sl解码 (服务端私钥签名 0x01填充, 客户端公钥运算还原):
       m = pow(sl_int, e, n)                 # 公钥指数运算(非私钥解密!)
       -> 去 PKCS#1 签名填充(00 01 FF.. 00) -> JSON:
          {"cKey":"hw2fdlwcj4cs1mx7","ckv":1,"key":"0cp4w1glgtgq96xn",
           "module":6,"nkv":2,"osVersion":3}
    3) 数据加密 y9x8y7z:
       AES-128-CBC, key=cKey(16字符UTF8), iv="1g3qqdh4jvbskb9x"(固定),
       padding=PKCS7, 输出base64; 请求体form: {secretStr, dateFormate}

## 关键洞察 (2026-10-14 实测)
    - kp.publicKey 是【硬编码服务端公钥】(3次实验完全相同), 非每次生成!
    - labc 是"用服务端公钥加密"(服务端用自己私钥解), 所以Python必须使用该公钥
    - sl 是"服务端私钥签名", 客户端 doPrivate 无p/q时退化 doPublic, pow(e)即可还原
    - Python AES 加密输出与 live JS 完全逐字节一致 (已验证 p3ROP4wG7ciy3Cxu5Fkveg==)

## 域映射(idMaps, 密钥ID)
    5=newexam-api / 11=studyservice+kgshare(默认) / 12=newcourse-api
    13=onlineservice-api / 6=AI智课域族

## 学习上报接口 (gateway/t/ 需加密; learning/* 部分免密)
    {base}/learning/saveCacheIntervalTimeV2      (缓存进度)
    {base}/learning/saveDatabaseIntervalTimeV2   (库进度)
    {base}/learning/findUnionAiId
    {base}/learning/saveUserStudyProcess         (免密白名单)

用法:
    from logic.zhihuishu.ai_smart_proto import AiSmartAPI
    api = AiSmartAPI(cookie_dict)
    ckey = api.get_key(6)                    # 拉取AI课密钥
    body = api.encrypt({"uid": "1"})         # -> {secretStr, dateFormate}
    resp = api.post_encrypted(path, payload) # 加密POST
"""
import base64
import json
import time
from typing import Any, Dict, Optional

import httpx

# 服务端公钥 (216字符, 2026-10-14 从 live 现场提取; 3次实验完全一致)
_SERVER_PUB_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCgfZmpLpPEpEFRKBe+ZjWJUjPe+7qg"
    "7pGqcfN3j2egJ8H2mrKwaEqZEnPnpi2O3hN8HRyaFozDOp8gwZiYfiIZjWy0Jr/FNAii"
    "KYh5bq0GsEn+ieMmRyJg/+i1rqizhvCXvFdrdGhFTw5EBwTpsGdwe1utdlrvIJUAFWj9"
    "Yh4qbQIDAQAB")

_BASE = "https://ai-smart-course-student-pro.zhihuishu.com"
_HAS_URL = "https://appcomm-user.zhihuishu.com/app-commserv-user/c/has"
_IV = b"1g3qqdh4jvbskb9x"     # 固定IV(源码确认)
# kg-ai-run域(2026-10-14 live抓包确认): AI课学习主域
_KG_RUN = "https://kg-ai-run.zhihuishu.com/run/gateway/t"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/143.0.7499.192 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://ai-smart-course-student-pro.zhihuishu.com/",
}


class AiSmartAPI:
    """AI智课协议客户端: 服务端公钥RSA交换 + sl公钥运算还原 + AES-CBC"""

    def __init__(self, cookies: Optional[Dict[str, str]] = None,
                 timeout: float = 30.0):
        self._cli = httpx.Client(
            cookies=cookies or {}, timeout=timeout,
            verify=False, follow_redirects=True, headers=dict(_HEADERS))
        self._pub = None
        self._cKey: Dict[int, str] = {}
        self._cKeyInfo: Dict[int, Dict[str, Any]] = {}

    # ---------- 服务端公钥 ----------
    def _load_pub(self):
        if self._pub is not None:
            return self._pub
        from cryptography.hazmat.primitives.serialization import (
            load_der_public_key)
        self._pub = load_der_public_key(base64.b64decode(_SERVER_PUB_B64))
        return self._pub

    # ---------- labc: 获取密钥(实测验证版) ----------
    def get_key(self, key_id: int = 6) -> str:
        """labc(id): 返回cKey(AES-128密钥, 16字符)

        uid = PKCS1v15(服务端公钥, {"module":id}) -> GET has -> rt.sl
        -> pow(sl,e,n) -> 去签名填充 -> JSON -> cKey
        """
        if key_id in self._cKey:
            return self._cKey[key_id]
        from cryptography.hazmat.primitives.asymmetric import padding
        pub = self._load_pub()
        payload = json.dumps({"module": key_id}, separators=(",", ":"))
        uid = base64.b64encode(
            pub.encrypt(payload.encode("utf-8"), padding.PKCS1v15())).decode()
        r = self._cli.get(_HAS_URL, params={"uid": uid})
        data = r.json()
        sl = ""
        if isinstance(data, dict):
            rt = data.get("rt")
            if isinstance(rt, dict):
                sl = str(rt.get("sl") or "")
        if not sl or len(sl) < 100:
            raise RuntimeError("labc失败: %s" % str(data)[:200])
        info = self._decode_sl(sl)
        ckey = str(info.get("cKey") or "")
        if not ckey:
            raise RuntimeError("sl解码无cKey: %s" % str(info)[:200])
        self._cKey[key_id] = ckey
        self._cKeyInfo[key_id] = info
        return ckey

    def _decode_sl(self, sl_b64: str) -> Dict[str, Any]:
        """sl解码: pow(sl, e, n) + 去PKCS#1签名填充(兼容0x01/0x02)"""
        pub = self._load_pub()
        nums = pub.public_numbers()
        n, e = nums.n, nums.e
        k = (n.bit_length() + 7) // 8
        m = pow(int.from_bytes(base64.b64decode(sl_b64), "big"),
                e, n).to_bytes(k, "big")
        i = 0
        while i < len(m) and m[i] == 0:
            i += 1
        if i < len(m) and m[i] == 1:          # 签名填充 00 01 FF..FF 00
            i += 1
            while i < len(m) and m[i] == 0xFF:
                i += 1
            i += 1
        elif i < len(m) and m[i] == 2:        # 加密填充 00 02 PS 00
            i += 1
            while i < len(m) and m[i] != 0:
                i += 1
            i += 1
        return json.loads(m[i:].decode("utf-8", "ignore"))

    # ---------- AES数据加密(y9x8y7z) ----------
    def encrypt(self, payload: Any, key_id: int = 6) -> Dict[str, str]:
        """加密请求体: AES-128-CBC(json, cKey, iv固定) -> {secretStr, dateFormate}

        实测: 与 live JS 输出逐字节一致.
        """
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        ckey = self.get_key(key_id)
        j = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        enc = AES.new(ckey.encode("utf-8")[:16], AES.MODE_CBC, _IV).encrypt(
            pad(j.encode("utf-8"), 16))
        return {"secretStr": base64.b64encode(enc).decode("ascii"),
                "dateFormate": str(int(time.time() * 1000))}

    # ---------- 业务请求 ----------
    def post_encrypted(self, path: str, payload: Any,
                       key_id: int = 6) -> Dict[str, Any]:
        """POST加密请求: form-urlencoded(secretStr+dateFormate)"""
        body = self.encrypt(payload, key_id)
        r = self._cli.post(_BASE + path, data=body)
        try:
            return r.json()
        except Exception:
            return {"status": str(r.status_code), "raw": r.text[:300]}

    def post_plain(self, path: str, payload: Any) -> Dict[str, Any]:
        """POST免密请求(白名单接口如saveUserStudyProcess)"""
        r = self._cli.post(_BASE + path, json=payload)
        try:
            return r.json()
        except Exception:
            return {"status": str(r.status_code), "raw": r.text[:300]}

    def get_plain(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """GET免密请求"""
        r = self._cli.get(_BASE + path, params=params or {})
        try:
            return r.json()
        except Exception:
            return {"status": str(r.status_code), "raw": r.text[:300]}

    # ---------- kg-ai-run 域(AI课学习主域, 2026-10-14 live确认) ----------
    def _post_kg(self, path: str, payload: Any, key_id: int = 6,
                 with_uuid: bool = False) -> Dict[str, Any]:
        """POST kg-ai-run域: body={secretStr, date} (部分接口需uuid字段)"""
        body = self.encrypt(payload, key_id)
        ms = int(time.time() * 1000)
        req = {"secretStr": body["secretStr"], "date": ms}
        if with_uuid:
            # uuid从CASLOGC cookie取
            try:
                import urllib.parse
                raw = self._cli.cookies.get("CASLOGC")
                uid = json.loads(urllib.parse.unquote(
                    raw or "{}")).get("uuid", "")
            except Exception:
                uid = ""
            payload = dict(payload or {})
            payload.setdefault("uuid", uid)
            payload.setdefault("date", ms)
            body = self.encrypt(payload, key_id)
            req = {"secretStr": body["secretStr"], "date": ms}
        r = self._cli.post(_KG_RUN + path, json=req)
        try:
            return r.json()
        except Exception:
            return {"status": str(r.status_code), "raw": r.text[:300]}

    def get_is_memo(self, course_id: str) -> Dict[str, Any]:
        """试做标记(kg): {courseIds:[...]}"""
        ms = int(time.time() * 1000)
        return self._post_kg("/common/course/get-is-memo",
                             {"courseIds": [course_id], "dateFormate": ms})

    def get_course_map_uid(self, course_id: str) -> Dict[str, Any]:
        """课程mapUid(kg): {"courseId":...} -> data.mapUid"""
        return self._post_kg("/common/course/get-course-mapUid",
                             {"courseId": course_id})

    def list_knowledge_theme(self, course_id: str, class_id: str) -> Dict[str, Any]:
        """知识树(kg): 返回courseThemeList(含knowledgeList/knowledgeId/studyProgress)"""
        return self._post_kg("/stu/knowledge-study/list-knowledge-theme",
                             {"courseId": course_id, "classId": class_id})

    def study_record(self, course_id: str, class_id: str,
                     knowledge_id: str) -> Dict[str, Any]:
        """学习登记(kg): {uuid,courseId,classId,knowledgeId,date} (实测code:200)"""
        ms = int(time.time() * 1000)
        return self._post_kg("/stu/studyRecord/study", {
            "courseId": course_id, "classId": class_id,
            "knowledgeId": knowledge_id}, with_uuid=True)

    def study_report(self, course_id: str, class_id: str, knowledge_id: str,
                     watch_uid: str, video_id: str = "") -> Dict[str, Any]:
        """学习深度上报(kg): 需WatchUId-key+视频资源ID(旧reverse探针保留)"""
        ms = int(time.time() * 1000)
        return self._post_kg("/stu/studyRecord/report", {
            "courseId": course_id, "classId": class_id,
            "knowledgeId": knowledge_id, "watchUId": watch_uid,
            "videoId": video_id}, with_uuid=True)

    # ---------- 完整学习链(2026-10-14 live真机披包确认) ----------
    def list_knowledge_resource(self, course_id: str, class_id: str,
                                knowledge_id: str) -> Dict[str, Any]:
        """知识点资源列表(kg): data.resourceList[].resourcesDetail.resourcesUid"""
        ms = int(time.time() * 1000)
        return self._post_kg("/stu/resources/list-knowledge-resource", {
            "courseId": course_id, "classId": class_id,
            "knowledgeId": knowledge_id, "dateFormate": ms})

    def get_knowledge_video_time(self, course_id: str, class_id: str,
                                 knowledge_id: str) -> Dict[str, Any]:
        """已学视频时长(kg): {courseId,knowledgeId,classId}"""
        return self._post_kg("/stu/studyRecord/get-knowledge-video-time", {
            "courseId": course_id, "knowledgeId": knowledge_id,
            "classId": class_id})

    def study_start(self, course_id: str, knowledge_id: str,
                    resource_id: str = "") -> Dict[str, Any]:
        """学习上报(kg, 实测code:200): {courseId,resourceId,knowledgeId,source:1,studyFileType:2}"""
        ms = int(time.time() * 1000)
        return self._post_kg("/stu/studyRecord/study", {
            "courseId": course_id, "resourceId": resource_id or knowledge_id,
            "knowledgeId": knowledge_id, "source": 1, "studyFileType": 2,
            "dateFormate": ms})

    def study_completed(self, course_id: str, class_id: str,
                        knowledge_id: str, resources_uid: str = "",
                        watch_uid: int = 1) -> Dict[str, Any]:
        """完成上报(kg, 实测code:200): {courseId,knowledgeId,classId,resourcesUid,watchUId:1}"""
        ms = int(time.time() * 1000)
        return self._post_kg("/stu/studyRecord/completed", {
            "courseId": course_id, "knowledgeId": knowledge_id,
            "classId": class_id, "resourcesUid": resources_uid,
            "watchUId": int(watch_uid), "dateFormate": ms})

    def brush_knowledge(self, course_id: str, class_id: str,
                        knowledge_id: str, log=None) -> Dict[str, Any]:
        """单知识点刷课(完整链): 拉资源->study->completed

        返回 {study:bool, completed:bool}
        """
        res_uid = ""
        try:
            rr = self.list_knowledge_resource(
                course_id, class_id, knowledge_id)
            rl = ((rr.get("data") or {}).get("resourceList") or [])
            if rl:
                res_uid = str(((rl[0].get("resourcesDetail") or {})
                               .get("resourcesUid")) or "")
        except Exception:
            pass
        ok1 = False
        try:
            s = self.study_start(course_id, knowledge_id, res_uid)
            ok1 = s.get("code") == 200
        except Exception:
            pass
        if log:
            try:
                log("  %s study=%s res=%s" %
                    (knowledge_id[-8:], ok1, res_uid[-8:]))
            except Exception:
                pass
        time.sleep(0.35)
        ok2 = False
        try:
            c = self.study_completed(
                course_id, class_id, knowledge_id, res_uid)
            ok2 = c.get("code") == 200
        except Exception:
            pass
        if log:
            try:
                log("  %s completed=%s" % (knowledge_id[-8:], ok2))
            except Exception:
                pass
        return {"study": ok1, "completed": ok2, "resourcesUid": res_uid}

    # ---------- 学习时长上报(2026-10-14 recordTime.js解码) ----------
    def record_page_time(self, course_id: str, knowledge_id: str,
                         class_id: str, study_second: int = 10) -> Dict[str, Any]:
        """页面学习时长上报(kg): {courseId,userPage,studySecond,updateTime}

        页面每10分钟/卸载时上报 studySecond=10; 直接循环调用实测可写入
        video-time(但服务端有窗口限流, 需多轮沉淀)。
        """
        ms = int(time.time() * 1000)
        upage = "/learnPage/%s/%s/%s" % (course_id, knowledge_id, class_id)
        return self._post_kg("/stu/task/record-student-page-time", {
            "courseId": course_id, "userPage": upage,
            "studySecond": int(study_second), "updateTime": ms})

    # ---------- 视频实时进度上报(2026-10-14 live播放捕获, 完整参数) ----------
    def report_video_progress(self, course_id: str, class_id: str,
                              knowledge_id: str, file_id: int,
                              last_watch_time: int, study_total_time: int = 10,
                              watch_uid: int = 1) -> Dict[str, Any]:
        """视频进度上报(kg, 实测code:200): 播放器每10-30秒调用

        fileId: 视频文件ID(播放器体系, 与resourcesFileId不同)
        lastWatchTime: 当前播放位置秒数; studyTotalTime: 本次增量(固定10)
        """
        ms = int(time.time() * 1000)
        return self._post_kg("/stu/studyRecord/report", {
            "courseId": course_id, "classId": class_id, "fileId": int(file_id),
            "studyTotalTime": int(study_total_time),
            "lastWatchTime": int(last_watch_time), "knowledgeId": knowledge_id,
            "shareCourseId": "", "watchUId": int(watch_uid),
            "nodeType": 0, "dateFormate": ms})

    def study_heartbeat(self, course_id: str, class_id: str, knowledge_id: str,
                        file_id: int, study_time: float, last_watch_time: int) -> Dict[str, Any]:
        """学习心跳(kg, 实测code:200): {studyFileType:1(视频), fileId, studyTime, lastWatchTime}"""
        ms = int(time.time() * 1000)
        return self._post_kg("/stu/studyRecord/study", {
            "courseId": course_id, "classId": class_id,
            "knowledgeId": knowledge_id, "source": 1, "studyFileType": 1,
            "fileId": int(file_id), "studyTime": float(study_time),
            "lastWatchTime": int(last_watch_time), "dateFormate": ms})

    def brush_video_knowledge(self, course_id: str, class_id: str,
                              knowledge_id: str, log=None) -> Dict[str, Any]:
        """视频型知识点刷课(2026-10-15 终极版, 实测prog 0→100%)

        ★完整公式(缺一不可):
          1) 前置: 无头浏览器打开 learnPage/{cid}/{kid}/{cls} 完成"访问注册"
             (纯HTTP无效—SPA壳未执行JS; 必须浏览器JS执行, 推荐nodriver)
          2) 本方法: 全部视频资源(type=1且有time)逐个report序列+study心跳
             + 全部资源(文本/视频/PPT)逐个completed
        注: 多视频知识点(如经络系统7视频)穷举全部;
            超长多视频仍有单轮限流, 需多轮时间沉淀.
        """
        # 1. 拉资源: 收集全部视频(type=1且time>0)与全资源uid
        vids = []
        ruids = []
        file_id = 0
        total = 0
        res_uid = ""
        try:
            rr = self.list_knowledge_resource(
                course_id, class_id, knowledge_id)
            rl = ((rr.get("data") or {}).get("resourceList") or [])
            for x in rl:
                d = x.get("resourcesDetail") or {}
                _ru = str(d.get("resourcesUid") or "")
                if _ru:
                    ruids.append(_ru)
                _rt = d.get("resourcesType")
                _tm = int(d.get("resourcesTime") or 0)
                if _rt == 1 and _tm > 0 and int(d.get("resourcesFileId") or 0):
                    vids.append((int(d.get("resourcesFileId") or 0), _tm))
                if not res_uid:
                    res_uid = str(d.get("resourcesUid") or "")
        except Exception:
            pass
        # 2. 全部视频逐个report序列+心跳
        ok_r = ok_s = 0
        for _fid, _tot in vids:
            if not _fid or _tot <= 0:
                continue
            _step = max(10, _tot // 30)
            for t in range(0, _tot + 1, _step):
                try:
                    r1 = self.report_video_progress(course_id, class_id,
                                                    knowledge_id, _fid, t, 10)
                    if r1.get("code") == 200:
                        ok_r += 1
                except Exception:
                    pass
            try:
                r2 = self.study_heartbeat(course_id, class_id, knowledge_id,
                                          _fid, float(_tot), _tot)
                if r2.get("code") == 200:
                    ok_s += 1
            except Exception:
                pass
        # 3. 全部资源逐个completed
        ok_c = 0
        for _uid in (ruids or ([res_uid] if res_uid else [])):
            if not _uid:
                continue
            try:
                c = self.study_completed(
                    course_id, class_id, knowledge_id, _uid)
                if c.get("code") == 200:
                    ok_c += 1
            except Exception:
                pass
            time.sleep(0.2)
        if log:
            try:
                log("  %s vids=%d rep=%d hb=%d comp=%d/%d" % (
                    knowledge_id[-8:], len(vids), ok_r, ok_s, ok_c, len(ruids)))
            except Exception:
                pass
        return {"videos": len(vids), "report": ok_r, "heartbeat": ok_s,
                "completed": ok_c, "resources": len(ruids),
                "resourcesUid": ruids[0] if ruids else ""}

    def brush_knowledge_full(self, course_id: str, class_id: str,
                             knowledge_id: str, rounds: int = 3,
                             log=None) -> Dict[str, Any]:
        """单知识点完整刷课(含时长): 资源->record-time循环->study->completed

        rounds: 时长上报轮数(每轮=一次record_page_time, 限流下多轮沉淀)
        """
        res_uid = ""
        try:
            rr = self.list_knowledge_resource(
                course_id, class_id, knowledge_id)
            rl = ((rr.get("data") or {}).get("resourceList") or [])
            if rl:
                res_uid = str(((rl[0].get("resourcesDetail") or {})
                               .get("resourcesUid")) or "")
        except Exception:
            pass
        ok_t = 0
        for _ in range(max(1, int(rounds))):
            try:
                rt = self.record_page_time(course_id, knowledge_id, class_id)
                if rt.get("code") == 200:
                    ok_t += 1
            except Exception:
                pass
            time.sleep(0.3)
        ok1 = ok2 = False
        try:
            s = self.study_start(course_id, knowledge_id, res_uid)
            ok1 = s.get("code") == 200
        except Exception:
            pass
        time.sleep(0.35)
        try:
            c = self.study_completed(
                course_id, class_id, knowledge_id, res_uid)
            ok2 = c.get("code") == 200
        except Exception:
            pass
        if log:
            try:
                log("  %s time=%d study=%s comp=%s" % (
                    knowledge_id[-8:], ok_t, ok1, ok2))
            except Exception:
                pass
        return {"time": ok_t, "study": ok1, "completed": ok2,
                "resourcesUid": res_uid}

    # ---------- 掌握度链(2026-10-15 全解) ----------
    # 机制: 掌握度=知识点的"考点测试"(examTestId体系)的正确率;
    #       masteryPercentage全0的根因=课程未配置/未开放测试任务(如本账号 get-all-exam-todo-tasks=[])
    #       43个 nodeFreeExam(免考) + 158个 nodeNotStudy(无测试) 属课程自身配置

    def get_mastery_statistics(self, course_id: str, class_id: str) -> Dict[str, Any]:
        """课程掌握度统计: →{nodeSize,meanMasteryPercentage,nodeGood/NormaL/Bad,nodeFreeExam...}"""
        return self._post_kg("/mastery-statistics/get-mastery-statistics",
                             {"courseId": course_id, "classId": class_id})

    def get_knowledge_mastery_stat(self, course_id: str, knowledge_id: str,
                                   class_id: str = "") -> Dict[str, Any]:
        """知识点掌握度: →{questionNum,correctNum,mastery,masteryHigh,masteryChange,paperId}"""
        pay = {"courseId": course_id, "knowledgeId": knowledge_id}
        if class_id:
            pay["classId"] = class_id
        return self._post_kg("/mastery-statistics/get-knowledge-mastery-stat", pay)

    def get_exam_todo_tasks(self, course_id: str, class_id: str) -> Dict[str, Any]:
        """待办考试/测试任务: →[]表示无测试任务(掌握度无法提升的原因)"""
        return self._post_kg("/task/v2/get-all-exam-todo-tasks",
                             {"courseId": course_id, "classId": class_id})

    # ---------- 任务链(2026-10-15 全解, kg-run-student域) ----------
    # 发现: "任务·作业·考试"Tab数据源=kg-run-student域; 任务含examTestId/examPaperId(可接考试链)
    # 实证: 中医护理学"六腑与奇恒之腑-小练习"(taskId=817925/examTestId=4296170/examPaperId=415675479/55分/已过期)

    _KR_STU = "https://kg-run-student.zhihuishu.com/student/gateway/t"

    def _post_kr(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """kg-run-student域POST(同key6加密; 用self._cli带cookie, 否则恒401)"""
        ms = int(time.time() * 1000)
        try:
            secret = self.encrypt(payload, 6)["secretStr"]
            r = self._cli.post(self._KR_STU + path,
                               json={"secretStr": secret, "date": ms})
            return r.json()
        except Exception:
            return {}

    def get_task_list(self, course_id: str, status: int = 0,
                      task_type: int = 2) -> Dict[str, Any]:
        """任务列表(status: 0=未完成 1=已完成; task_type: 2=考试型)
        →data[] 每项含 id/taskName/examTestId/examPaperId/score/startTime/endTime"""
        return self._post_kr("/task/taskList", {
            "courseId": course_id, "taskType": task_type,
            "taskName": "", "status": status})

    def check_task(self, task_id: int, course_id: str) -> Dict[str, Any]:
        """检查任务状态: →data=1(进行中/有效)"""
        return self._post_kr("/stu/task/check-task", {
            "taskId": int(task_id), "courseId": course_id})

    def save_student_point_log(self, course_id: str, class_id: str,
                               task_id: int) -> Dict[str, Any]:
        """记录任务学习点(进入任务页时调用)"""
        ms = int(time.time() * 1000)
        return self._post_kg("/stu/task/saveStudentPointLog", {
            "courseId": course_id, "classId": class_id, "taskId": int(task_id)})

    # ---------- 批阅回读→题库更正(2026-10-15 框架, 待"回答情况"live样本补全字段) ----------
    # 需求来源(用户): "看回答情况时能看到错题正确答案" -> 采集正确答案写入题库(对齐MOGO"官库先采集")
    # 已知: 批阅详情接口在kg-run-student任务域(getStuAnswerRecordList/openExamNewDetail等),
    #       但直连返回401(需页面级额外鉴权头) -> 待1次live抓"查看回答情况"请求补全头/参数后启用。

    def harvest_answers(self, task_id: int, course_id: str,
                        class_id: str = "", log=None) -> int:
        """批阅回读采集正确答案入题库(框架)

        流程(待样本补全): getStuAnswerRecordList(答题记录) -> 逐题取题干+correct选项
        -> bridge缓存(题目归一化->答案文本). 返回入库条数.
        """
        result = 0
        try:
            r = self._post_kr("/task/getStuAnswerRecordList",
                              {"taskId": int(task_id), "courseId": course_id})
            if r.get("code") != 200:
                if log:
                    try:
                        log("  批阅回读暂不可用(%s), 待live样本补鉴权头" % r.get("message"))
                    except Exception:
                        pass
                return 0
            records = ((r.get("data") or {}).get("records")
                       or (r.get("data") or {}).get("list") or [])
            from logic.core.answer_bridge import bridge_cache_results
            _pairs = []
            for rec in (records if isinstance(records, list) else []):
                if not isinstance(rec, dict):
                    continue
                q = str(rec.get("content") or rec.get("questionContent") or "")
                opts = rec.get("options") or rec.get("optionVos") or []
                correct = [str(o.get("content", "")) for o in opts
                           if isinstance(o, dict) and o.get("isCorrect") == 1]
                if q and correct:
                    _pairs.append({"q_text": q, "answer": ";".join(correct),
                                   "src": "平台批阅回读", "q_type": ""})
            if _pairs:
                result = bridge_cache_results(_pairs)
        except Exception:
            pass
        return result

    # ---------- 批阅回读(回答情况/题库更正, 2026-10-15 定位) ----------
    # 面试实锤: examloop(回答情况SPA)拦截器域映射表显示
    #   "uuid加密组(6)": kg-ai-run.zhihuishu.com/run/gateway/t/tch/read/over/AnswerReview
    # 实测: 接口存在(code500"小插曲"=参数未被接受), 参数白名单待一轮live(点开"回答情况"页时抓)

    def answer_review(self, exam_test_id=None, exam_paper_id=None,
                      task_id=None, course_id: str = "") -> Dict[str, Any]:
        """批阅回读(回答情况): 尝试常见参数组合 → 提取正确答案(optionVos[].isCorrect)

        成功后返回 {"questions": [...答题卡条目...]} 便于题库更正。
        注: 参数白名单待live定型, 当前多组合尝试。
        """
        variants = []
        if exam_test_id and exam_paper_id:
            variants.append({"examTestId": exam_test_id, "examPaperId": exam_paper_id,
                             "courseId": course_id})
        if task_id:
            variants.append({"taskId": task_id, "courseId": course_id})
            if exam_test_id:
                variants.append({"taskId": task_id, "examTestId": exam_test_id,
                                 "examPaperId": exam_paper_id, "courseId": course_id})
        import httpx as _hx
        for pay in variants:
            try:
                secret = self.encrypt(pay, 6)["secretStr"]
                r = self._cli.post(
                    "https://kg-ai-run.zhihuishu.com/run/gateway/t/tch/read/over/AnswerReview",
                    json={"secretStr": secret, "date": int(time.time() * 1000)})
                j = r.json()
                if j.get("code") == 200 and j.get("data"):
                    return j
            except Exception:
                continue
        return {}

    # ---------- 批阅回读链(2026-10-15 决战全胜, 参数白名单100%实锤) ----------
    # 入口: kg-run-student openExamTestDetail(=考试详情/批阅数据总入口, 实测code200)
    # 实测参数: {examId, examTestId, studentId, taskId, classId, courseId}
    # 关键门控: isLookAnswer(0=平台禁止看答案; 1=可看) / isAllowShowDetail(1=可看详情)
    # 由来: taskList(已完成) -> 卡片状态btn -> examDetail页 -> openExamTestDetail

    def open_exam_test_detail(self, exam_id, exam_test_id, student_id,
                              task_id, class_id, course_id) -> Dict[str, Any]:
        """考试详情/批阅回读入口(实锤200)
        -> data{paperId, examName, totalScore, isLookAnswer, isAllowShowDetail,
                canRestart, examStatus...}"""
        return self._post_kr("/stu/task/v2/openExamTestDetail", {
            "examId": int(exam_id), "examTestId": int(exam_test_id),
            "studentId": int(student_id), "taskId": int(task_id),
            "classId": str(class_id), "courseId": str(course_id)})

    def review_exam_task(self, course_id: str, class_id: str, status: int = 1) -> list:
        """批阅回读全链: taskList -> openExamTestDetail(逐任务)
        -> [{taskName, examId, examTestId, isLookAnswer, totalScore...}]"""
        out = []
        tl = self.get_task_list(course_id, status=status)
        for t in (tl.get("data") or []):
            if not isinstance(t, dict):
                continue
            _sid = t.get("userId") or 0
            try:
                d = self.open_exam_test_detail(t.get("examId"), t.get("examTestId"),
                                               _sid, t.get("id"), class_id, course_id)
                dd = d.get("data") or {}
                dd["taskName"] = t.get("taskName")
                dd["taskId"] = t.get("id")
                out.append(dd)
            except Exception:
                continue
        return out

    # ---------- 掌握度/知识点作业链(2026-10-15 从pjm314159/zhs参考确认) ----------
    # 关键: AI课的"作业"=掌握度来源; questions-paper拿"知识点作业"(examTestId/paperId/masteryScore)
    # 实测: 中医护理学"近代..."-> masteryScore=0, examTestId=3978241, paperId=418054528, questionNum=3

    def query_knowledge_paper(self, course_id, class_id, knowledge_id) -> Dict[str, Any]:
        """知识点作业(掌握度): -> {masteryScore, highMasteryScore, examTestId, paperId, questionNum}
        scMapId=courseId; courseId/classId=班级id(注意该平台命名颠倒)"""
        return self._post_kg("/stu/exam/questions-paper", {
            "scMapId": int(course_id), "courseId": int(class_id),
            "classId": int(class_id), "knowledgeId": int(knowledge_id)})
