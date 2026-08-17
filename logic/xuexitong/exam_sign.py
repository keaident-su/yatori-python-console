# -*- coding: utf-8 -*-
"""
学习通考试客户端签名 - 对齐 APP libsecuritylib.so 的 web_request_sign 算法

逆向依据(Yuuki: https://yuuki.cool/posts/xvexitong/):
- 消息构造: JSON对象按key字典序排序后, 依次拼接 key+str(value) 字节流
  (bool→"true"/"false", None→"", 嵌套对象→紧凑JSON字符串)
- 签名: SHA256(message) → RSA PKCS#1 v1.5 用APK内嵌私钥签名 → base64

考试"开始考试"页(CLIENT_FORM_SIGN)的签名参数:
- cxcid: 设备特征码(在APP内通过 CLIENT_DEVICE_FLAG 获取, 即Misaka工具页
  https://doc.micono.eu.org/tools/device 取到的flagInfo)
- cxtime: 签名时间戳(毫秒)
- signk: RSA签名(base64)
- signt/_signcode/_signc/_signe: 签名辅助参数
"""
import base64
import json
import time
from typing import Any, Dict, Optional

try:
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA256, SHA1
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

# APK内嵌RSA私钥(DER/PKCS#8, 来自 libsecuritylib.so 逆向)
EMBEDDED_PRIVATE_KEY_B64 = (
    "MIICeAIBADANBgkqhkiG9w0BAQEFAASCAmIwggJeAgEAAoGBAKKJT8YxQ8N4HPsREJK06k4+itt6wyCbNEUN5ENNUX0XFD//sUwvM12VfE9ANz9QM2rLhtwFTM6W/TKJzeGV2zY2+6HGK3ksvR9cY3bEcnm4IRDQzDCO+srhq0n6HRUXdrjp8SVImIowzTRPvsQ4iCrfx3vOyEXM4Nn6Rh4SlMKLAgMBAAECgYB0Edy/KxU6NL91Z6VPLxUX1T/yJoPL+CnmmloE2eU0kFOstFsXjal/zi2cpr4NX6eoPznKS5qi+V5NRe2ZiBunP4SiN6WZvkwYL4XCZBElstdW3/qdV4FWtCgtBqpacfOam9dT+d0q2rA4nbbpXOWhICYKfaBBG+C8IPZGfZRh0QJBAO/lNDi62pL2spQl4To1QAZUdPK5WyIlc1NEuHlXc+asBhlwI5SHvoBHXQ8+oLl6Zmj0piS9bAUu6sJB1Zj+WSkCQQCtcqGU0H645m1UzuC/Xxonnd//6eDXHdnMiOFnWdlJ9t2MhJ4qUfBmN+XH0bej+HvRl2DHPhKsJ5UegKmI7RCTAkEA2Gu69QL9dWBCMw0JZ+3qWMuQxfkakm+e3xw8IJwY352J0yEruC/OWQQInFwvu6UFBuLPkI2jCfoNqDqkbGXqIQJBAIBvXskEbqHaN2FSY8gx0vs9A47MD6sbNpknTsmqFaWYgMu5tCkgTcRTZfpGCBcKPB2iW46OH2ONV/WjTmbPLLMCQQCKMAapcf110Kwe5H6VapWD+zC0I2nFLYYF2g/ugaNvT0udASLnEmWZLeTR5nUcfaEfwci4B4hJUAwrPJQ7VBIi"
)


def _to_string(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    return str(v)


def build_message_from_obj(obj: Dict) -> bytes:
    """消息构造: key字典序排序后拼接 key+str(value) - 对齐 APP build_message_from_json"""
    keys = sorted(obj.keys())
    parts = []
    for k in keys:
        parts.append(str(k) + _to_string(obj[k]))
    return "".join(parts).encode("utf-8")


def rsa_sign_message(message: bytes, hash_alg: str = "SHA256") -> str:
    """RSA PKCS#1 v1.5 签名 - 对齐 APP web_request_sign"""
    if not _HAS_CRYPTO:
        raise RuntimeError("缺少pycryptodome依赖(pip install pycryptodome)")
    key = RSA.import_key(base64.b64decode(EMBEDDED_PRIVATE_KEY_B64))
    h = SHA256.new(message) if hash_alg.upper(
    ) == "SHA256" else SHA1.new(message)
    sig = pkcs1_15.new(key).sign(h)
    return base64.b64encode(sig).decode("ascii")


def compute_start_exam_sign(test_user_relation_id: str, class_id: str,
                            device_flag: str = "",
                            sign_config: Optional[Dict] = None,
                            message_mode: int = 0) -> Dict:
    """计算考试"开始考试"页(CLIENT_FORM_SIGN)的签名参数

    :param test_user_relation_id: 试卷页隐藏字段 testUserRelationId
    :param class_id: 试卷页隐藏字段 classId
    :param device_flag: 设备特征码(APP内 CLIENT_DEVICE_FLAG 获取的flagInfo,
                        通过 https://doc.micono.eu.org/tools/device 在APP内打开获取)
    :param sign_config: 试卷页隐藏字段 signConfig 解析出的JSON
    :param message_mode: 签名消息构造模式(多种候选，实测调优)
        0 = payload JSON {data.param, typeFlag, signConfig}
        1 = 仅 param 字符串 "startExam_{tuid}-{cid}"
        2 = typeFlag JSON 仅 {type, funckey}
    :return: {cxcid, cxtime, signt, signk, _signcode, _signc, _signe}
    """
    cxtime = int(time.time() * 1000)
    funckey = f"examSignatureCheck_{test_user_relation_id}-{class_id}-{cxtime}"
    param = f"startExam_{test_user_relation_id}-{class_id}"
    type_flag = {"type": "startExam", "funckey": funckey}

    if message_mode == 1:
        message = param.encode("utf-8")
    elif message_mode == 2:
        message = build_message_from_obj(type_flag)
    else:
        # CLIENT_FORM_SIGN 载荷: data.param + typeFlag + signConfig
        payload = {"data": {"param": param}, "typeFlag": type_flag}
        if sign_config:
            payload["signConfig"] = sign_config
        message = build_message_from_obj(payload)

    signk = rsa_sign_message(message)
    return {
        "cxcid": device_flag or "",
        "cxtime": str(cxtime),
        "signt": "",
        "signk": signk,
        "_signcode": "0",
        "_signc": "0",
        "_signe": "",
    }
