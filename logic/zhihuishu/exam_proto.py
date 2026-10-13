# -*- coding: utf-8 -*-
"""智慧树考试域协议客户端 (2026-10-13 固化, A方案成果)

## 加密体系 (已字节级验证)
    secretStr = base64(AES-128-CBC(json_bytes, key, iv, PKCS7))
    key = b"onbfhdyvz8x7otrp"  iv = b"1g3qqdh4jvbskb9x"
    请求: POST form = {"secretStr": <密文>, "date": <毫秒时间戳>}
    (无需RSA/设备签名; f分组免密, t分组即本加密)

## 域
    业务:  https://studentexam-api.zhihuishu.com/studentExam/gateway/t/v1
    taurus: https://taurusexam-api.zhihuishu.com/taurusExam/gateway/t/v1  (多数404, 少量可用)

## 已验证接口(200)
    /exam/getCourseName            {recruitId}
    /exam/getSingleRecruit         {recruitId}   -> 课程详情(id/name/courseId/起止)
    /student/getStuProgressRule    {recruitId, schoolId} -> {"makeUpStudent": "1"}
    /student/getStudentHomework    {recruitId, courseId, type} -> 作业/章测列表(已提交用type=2)

## JS bundle全谱(54个, 详见 ZHS_EXAM_PROTOCOL.md)
    /answer/submit /answer/saveStudentAnswer /answer/getStuAnswerInfoNew(批阅详情)
    /student/doExam /student/doHomework /student/lookHomework(拉卷)
    /student/getStudentFinalExam(期末) /student/getStudentOfflineExam
    /student/getStudentRoomExam /exam/getAllQuesitonAnalysis /exam/getExamType 等

用法:
    from logic.zhihuishu.exam_proto import ZhsExamAPI
    ex = ZhsExamAPI(cookie_dict)         # cookie_dict: {name: value}
    print(ex.get_single_recruit("431867"))
    print(ex.get_student_homework("431867", "1000125370", type=2))
"""
import base64
import json
import time
from typing import Any, Dict, Optional

import httpx

_KEY = b"onbfhdyvz8x7otrp"
_IV = b"1g3qqdh4jvbskb9x"
_BASE_T = ("https://studentexam-api.zhihuishu.com"
           "/studentExam/gateway/t/v1")
_BASE_TU = ("https://taurusexam-api.zhihuishu.com"
            "/taurusExam/gateway/t/v1")


def encrypt_params(payload: Dict[str, Any]) -> str:
    """secretStr = base64(AES-128-CBC(json, key, iv, PKCS7))"""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    j = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    enc = AES.new(_KEY, AES.MODE_CBC, _IV).encrypt(pad(j.encode("utf-8"), 16))
    return base64.b64encode(enc).decode("ascii")


class ZhsExamAPI:
    """智慧树考试域API客户端(纯协议, 固定key/iv加密)"""

    def __init__(self, cookies: Optional[Dict[str, str]] = None,
                 timeout: float = 30.0):
        self._cli = httpx.Client(
            cookies=cookies or {}, timeout=timeout,
            verify=False, follow_redirects=True)

    def _post(self, path: str, payload: Dict[str, Any],
              taurus: bool = False) -> Dict[str, Any]:
        base = _BASE_TU if taurus else _BASE_T
        r = self._cli.post(base + path, data={
            "secretStr": encrypt_params(payload),
            "date": str(int(time.time() * 1000)),
        })
        try:
            return r.json()
        except Exception:
            return {"status": str(r.status_code), "raw": r.text[:200]}

    # ---------- 已验证接口 ----------

    def get_course_name(self, recruit_id: str) -> Dict[str, Any]:
        return self._post("/exam/getCourseName", {"recruitId": recruit_id})

    def get_single_recruit(self, recruit_id: str) -> Dict[str, Any]:
        return self._post("/exam/getSingleRecruit", {"recruitId": recruit_id})

    def get_stu_progress_rule(self, recruit_id: str,
                              school_id: int = 2731) -> Dict[str, Any]:
        return self._post("/student/getStuProgressRule",
                          {"recruitId": recruit_id, "schoolId": school_id})

    def get_student_homework(self, recruit_id: str, course_id: str,
                             hw_type: int = 2) -> Dict[str, Any]:
        """作业/章测列表(已提交=2); 返回 rt.next=-1 表示列表尾"""
        return self._post("/student/getStudentHomework",
                          {"recruitId": recruit_id, "courseId": course_id,
                           "type": hw_type})

    # ---------- 待参数定型(JS已确认路径存在) ----------

    def get_student_final_exam(self, recruit_id: str, course_id: str,
                               **extra: Any) -> Dict[str, Any]:
        """期末考试列表
        2026-10-13 定型: 域=studentexam(taurus域同样存在但结果同);
        无期末考试数据的课程服务端会NPE(平台特性, 非参数错);
        有数据的课程正常返回。
        """
        p = {"recruitId": recruit_id, "courseId": course_id}
        p.update(extra)
        return self._post("/student/getStudentFinalExam", p)

    def look_homework(self, hw_id: int) -> Dict[str, Any]:
        """查看作业详情/拉卷(2026-10-13 结构定型)
        白名单实测: 仅支持"id"字段(int); 其他字段名→"传入参数异常";
        含id但值非有效作业→"aes加密参数异常"(=结构已被服务端接受, 只差有效数据)。
        hw_id 应取 [作业列表(getStudentHomework)中条目的真实作业id]。
        """
        return self._post("/student/lookHomework", {"id": int(hw_id)})

    def do_exam(self, exam_id: int, **extra: Any) -> Dict[str, Any]:
        """进入考试(2026-10-13 骨架: 参数白名单待样本; 已知须int型id类字段)"""
        p = {"id": int(exam_id)}
        p.update(extra)
        return self._post("/student/doExam", p)

    def get_stu_answer_info_new(self, **params: Any) -> Dict[str, Any]:
        """批阅详情/答案回读(参数待样本定型)"""
        return self._post("/answer/getStuAnswerInfoNew", params)
