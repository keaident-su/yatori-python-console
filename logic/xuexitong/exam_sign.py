# -*- coding: utf-8 -*-
"""
学习通考试客户端签名 - 对齐 APP libsecuritylib.so 的 webRequestSign 算法

逆向依据(多重证据):
1. 社区公开分析:
   - 消息构造: JSON对象按key字典序排序后, 依次拼接 key+str(value) 字节流
     (bool→"true"/"false", None→"", 嵌套对象→紧凑JSON字符串)
   - 签名: SHA256(message) → RSA PKCS#1 v1.5 用APK内嵌私钥签名 → base64
2. 学习通7.0.4版APK逆向(2026-10-02, chaoxing_app_7.0.4):
   - libsecuritylib.so JNI导出确认: SecurityLib_webRequestSign(Web请求签名)、
     SecurityLib_verifyJsSign(JS签名验证)、SecurityLib_cryptUserAgent(UA加密)、
     CxDevice_getDeviceInfo/decryptDeviceInfo(设备信息获取与解密)
   - 内部符号: Device::getSignature/getAndroidId/getMediaDrmId、
     rsa_util::private_key_sign/private_key_encrypt、RSA_sign/SHA256(OpenSSL)
   - rsa_util::format_public_key/format_private_key 说明公/私钥是运行时
     由PEM模板(-----BEGIN PRIVATE KEY-----)动态格式化, so内嵌PEM模板
   - 设备链路(7.0.4确认): 多源设备采集(AndroidId/MediaDrm/IMEI/蓝牙/BSSID/基站)
     → RiskStub设备画像JSON → 9项风控检查(Root/模拟器/代理/VPN/屏幕共享等)
     → 服务端状态+本地缓存 → 安全库加密/签名 → 派生身份值(非单一明文)
3. 参考项目对照: do_signt_signk生成signk+signt双值; 消息模板
   "cxcid{0}cxtime{1}param{2}paramToken{3}{4}"; URL用_signcode=1&_signc=1

考试"开始考试"页(CLIENT_FORM_SIGN)的签名参数:
- cxcid: 设备特征码(APP内通过CLIENT_DEVICE_FLAG获取; 7.0.4确认为
  多源画像派生的加密值, 非简单设备ID; yatori 用 Base64(AES(UUID)) 模拟)
- cxtime: 签名时间戳(毫秒)
- signk: RSA签名(base64)
- signt/_signcode/_signc/_signe: 签名辅助参数

注: 7.0.4静态分析未能在离线包中还原 webRequestSign 的完整消息字节流
(业务代码在壳加密载荷内), 本文件保留 message_mode 多模式候选 + 实测调优。

==================== 考试H5人脸全链路逆向(2026-10-05, 服务端JS实拉) ====================
来源: 实拉 exam-ans 页面JS (exam-sign-min.js / start page / to-face-compare页) 分析得到:

1. 全部前端签名函数(均通过 jsBridge.postNotification('CLIENT_FORM_SIGN')交由APP原生RSA签):
   - startExamSignature:   param = "startExam_{tuid}-{classId}"(? 实测验证过✓)
   - faceCompareSignature: param = "faceCompare_{tuid}-{classId}-{currentFaceId}-{sessionId}" (★以前错用startExam的param)
   - submitExamSignature:  param = "submitExam_{tuid}-{classId}-{enterPageTime}-{qid}-{答案值}"
     (★2026-10-07实测权威格式; 旧记录{blankNum}-{flag}为误解)
   - notifyExamSignatureCheck: param = "examSignatureCheck_{tuid}-{classId}"
   - keeperLogSignature:   param = "keeperLog_{tuid}-{classId}-{时间戳}"
   回调约定: window[funckey](cxcid,cxtime,signk,signt,code,count,ecode)
   (signk=paramToken, signt=signToken, count=checkCount, ecode=extraInfo.code)

2. face-compare 完整调用参数集(前端 faceCompare() 函数实测提取):
   relationid, courseId, classId, currentFaceId, liveDetectionStatus, collectStatus,
   recogType, _provider=0, sessionId, SenseDetectionStatus, tk, cpi, _d=mobile;
   带签名时追加: _signcode=code, _signc=count, _signe=ecode, signk, cxcid, cxtime, signt
   其中 tk = cxcid + '_' + cxtime + '_' + signToken (来自原生人脸object)

3. 考试人脸两套链路(关键结论):
   正式监考卷: APP原生人脸(CLIENT_FACE_RECOGNITION_BLINK) → 原生拿facekey
     → jsBridge 'CLIENT_WEB_EXTRAINFO'(typeflag=ENTER_EXAM, info.facekey) → H5带facekey直接start
     —— face-compare 仅作无APP时的降级替补, 且对正式监考卷被服务端拒绝("无效参数")
   自测卷(如测试7): 无原生环境时 face-compare 开放 → 换基准法可100分拿facekey → 全自动✓
   实测穷举(2026-10-05): APTX等正式卷 face-compare 无论参数(6变体)/UA/签名(4组合)均拒;
     测试7均SUCCESS——差异在服务端考试数据层, 纯协议无法跨过正式卷的人脸关。

==================== 正式卷"提交签名"实测格式(2026-10-07) ====================
来源: 热心人士提供的参考脚本 + 实测对照;
  "进卷可过但提交被拒(请使用学习通APP最新版本)"的全部差异点:
1. param   = "submitExam_{tuid}-{classId}-{enterPageTime}-{qid}-{答案值}"
   (enterPageTime取自题目页hidden; 答案值为表单最终值: 单选字母/多选拼接/判断true|false/填空累加/简答文本)
2. URL签名 = _csign=1&_signcode=true&_signc=1&_signe=&_signk={sig}&_cxcid={cid}&_cxtime={cx}&_signt={signt}
   ——★_signcode为字符串"true"(非"1"); pos=留空; version=1
3. form同步携带无下划线版 cxcid/cxtime/signt/signk (官方APP双签名)
4. Referer必须为题目页URL; 交卷=末题页 tempSave=false 重新提交
5. 签名链同start: sig=RSA("param"+param), signt=MD5(cxcid..cxtime..param..paramToken..sc)
   ——同一把内嵌私钥, 无需新密钥。
6. 人脸是start硬前置: 正式人脸卷v2签名start直接返回"人脸识别对比不通过,不允许进入考试"
   (无facekey无窗口; 测试7能过因face-compare开放→换基准法拿facekey)。
==============================================================================
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
# 2026-10-21 用户定夺: 考试签名RSA私钥必须保留在程序中(撤销剥离), 硬编码如下
EMBEDDED_PRIVATE_KEY_B64 = (
    "MIICeAIBADANBgkqhkiG9w0BAQEFAASCAmIwggJeAgEAAoGBAKKJT8YxQ8N4HPsREJK06k4+itt6wyCbNEUN5ENNUX0XFD//sUwv"
    "M12VfE9ANz9QM2rLhtwFTM6W/TKJzeGV2zY2+6HGK3ksvR9cY3bEcnm4IRDQzDCO+srhq0n6HRUXdrjp8SVImIowzTRPvsQ4iCrf"
    "x3vOyEXM4Nn6Rh4SlMKLAgMBAAECgYB0Edy/KxU6NL91Z6VPLxUX1T/yJoPL+CnmmloE2eU0kFOstFsXjal/zi2cpr4NX6eoPznK"
    "S5qi+V5NRe2ZiBunP4SiN6WZvkwYL4XCZBElstdW3/qdV4FWtCgtBqpacfOam9dT+d0q2rA4nbbpXOWhICYKfaBBG+C8IPZGfZRh"
    "0QJBAO/lNDi62pL2spQl4To1QAZUdPK5WyIlc1NEuHlXc+asBhlwI5SHvoBHXQ8+oLl6Zmj0piS9bAUu6sJB1Zj+WSkCQQCtcqGU"
    "0H645m1UzuC/Xxonnd//6eDXHdnMiOFnWdlJ9t2MhJ4qUfBmN+XH0bej+HvRl2DHPhKsJ5UegKmI7RCTAkEA2Gu69QL9dWBCMw0J"
    "Z+3qWMuQxfkakm+e3xw8IJwY352J0yEruC/OWQQInFwvu6UFBuLPkI2jCfoNqDqkbGXqIQJBAIBvXskEbqHaN2FSY8gx0vs9A47M"
    "D6sbNpknTsmqFaWYgMu5tCkgTcRTZfpGCBcKPB2iW46OH2ONV/WjTmbPLLMCQQCKMAapcf110Kwe5H6VapWD+zC0I2nFLYYF2g/u"
    "gaNvT0udASLnEmWZLeTR5nUcfaEfwci4B4hJUAwrPJQ7VBIi"
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
        3 = 参考项目模板 "cxcid{cxcid}cxtime{cxtime}param{param}paramToken{cxtime}"
            (7.0.4对照: webRequestSign 可能采用同类"键值直接拼接"消息)
        4 = 扁平键值字典AJAZ风格 "cxcid{v}&cxtime={v}&param={v}&paramToken={v}"
            (7.0.4对照: Web请求签名可能带分隔符)
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
    elif message_mode == 3:
        # 参考项目模板: 键+值直接拼接(无分隔符无'=')
        msg = (f"cxcid{device_flag or ''}cxtime{cxtime}"
               f"param{param}paramToken{cxtime}")
        message = msg.encode("utf-8")
    elif message_mode == 4:
        # 键=值&拼接风格(带分隔符变体)
        msg = (f"cxcid={device_flag or ''}&cxtime={cxtime}"
               f"&param={param}&paramToken={cxtime}")
        message = msg.encode("utf-8")
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


# ==================== v2: APP真实签名链 ====================
# 来源: 2026-10 第三方实测脚本(学习通APP原生协议),
# 与 APP libsecuritylib.so 行为一致, 已实测验证:
#   登录 → SSO会话 → 设备指纹上报 → clientId公钥解密出(cid, sc)
#   → param="startExam_{tuid}-{cid}" → sig=RSA私钥签("param"+param)
#   → signt=MD5("cxcid{cid}cxtime{t}param{param}paramToken{sig}{sc}")
#   → start URL带 cxcid=cid&signt=&signk= → 302进卷

# 设备指纹上报公钥 (RSA-1024, SPKI DER; 服务端用对应私钥签发 clientId)
DEVICE_PUB_KEY_V2_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC79d8Ot0hCbxxSISC6x8SCwTBspFSz"
    "lLKHJUYqoFNu1TSRaw4hEYkOnvEaL1VyoxV6HXcDrzwYvaFZaZaPQPFnfCHZy5dQwxcmifgSHqS+oKXw40Ys4cVIqnU5d90S7EWSRdBglX489jlqVaNcQSkDx2TYmC+DbAq9FV/BU09ISQIDAQAB"
)

# APP 版本常量 (UA与设备画像使用)
APP_VERSION_V2 = "7.0.4"  # 2026-10-20: 对齐最新版真机(10995_342)
APP_BUILD_V2 = "11830_311"


def build_device_info_v2(imei: str = "", model: str = "MI 10",
                         os_ver: str = "12", version_code: str = "10995") -> bytes:
    """构造设备指纹上报JSON (APP原生字段集)

    关键: signatures 为 APK 签名指纹; deviceUniqueId/cdid/device_id 同值
    (sha256("com.chaoxing.mobile:{android_id}:{fingerprint}"))
    """
    import uuid as _uuid
    import hashlib as _hashlib
    android_id = _uuid.uuid4().hex[:16]
    fingerprint = ("Xiaomi/mi10/MI10:12/SKQ1.211006.001/"
                   "1234567:user/release-keys")
    duid = _hashlib.sha256(
        f"com.chaoxing.mobile:{android_id}:{fingerprint}".encode()
    ).hexdigest()
    info = {
        "deviceUniqueId": duid, "cdid": duid, "device_id": duid,
        "android_id": android_id, "mediaDrmId": "", "oaid": "",
        "platform": "android", "os_name": "android", "os_ver": os_ver,
        "os_lang": "zh-CN", "brand": "Xiaomi", "board": "mi10",
        "hardware": "qcom", "model": model, "cpu_ar": "arm64-v8a",
        "app_name": "com.chaoxing.mobile", "app_ver": APP_VERSION_V2,
        "versionCode": version_code,
        "signatures": ("1e27068798b6697821abbeb44a17da5483c4fb7fad7b9ce"
                       "7890465ed04d0cbe0"),
        "resolution": "1080*2340", "dpi": "2.75",
        "time_stamp": int(time.time() * 1000),
    }
    return json.dumps(info, separators=(",", ":"),
                      ensure_ascii=False).encode()


def rsa_encrypt_report_v2(plain: bytes) -> str:
    """设备画像 → RSA-1024 分块加密(每块117字节) → base64"""
    if not _HAS_CRYPTO:
        raise RuntimeError("缺少pycryptodome依赖")
    from Crypto.PublicKey import RSA as _RSA
    from Crypto.Cipher import PKCS1_v1_5 as _PKCS1_v1_5
    pub = _RSA.import_key(base64.b64decode(DEVICE_PUB_KEY_V2_B64))
    cipher = _PKCS1_v1_5.new(pub)
    cipher_text = b""
    for off in range(0, len(plain), 117):
        cipher_text += cipher.encrypt(plain[off:off + 117])
    return base64.b64encode(cipher_text).decode()


def rsa_decrypt_client_id_v2(client_id_b64: str) -> Dict[str, str]:
    """clientId(服务端私钥加密) → 公钥逐128字节数学解密 → {cid, sc}"""
    from Crypto.PublicKey import RSA as _RSA
    pub = _RSA.import_key(base64.b64decode(DEVICE_PUB_KEY_V2_B64))
    blob = base64.b64decode(client_id_b64)
    n, e = pub.n, pub.e
    dec_out = b""
    for off in range(0, len(blob), 128):
        m = pow(int.from_bytes(blob[off:off + 128], "big"), e, n).to_bytes(
            128, "big")
        if not (len(m) > 2 and m[0] == 0 and m[1] == 1):
            raise RuntimeError("clientId解密: PKCS1 v1.5 头不符")
        dec_out += m[m.index(b"\x00", 2) + 1:]
    return json.loads(dec_out)


def form_sign_v2(param: str) -> str:
    """CLIENT_FORM_SIGN: RSA PKCS1v15-SHA256 签("param"+param), base64

    注意: 消息是字面量前缀 "param" 拼接参数值(与APP树图消息一致)
    """
    if not _HAS_CRYPTO:
        raise RuntimeError("缺少pycryptodome依赖")
    msg = ("param" + param).encode("utf-8")
    key = RSA.import_key(base64.b64decode(EMBEDDED_PRIVATE_KEY_B64))
    sig = pkcs1_15.new(key).sign(SHA256.new(msg))
    return base64.b64encode(sig).decode("ascii")


def compute_signt_v2(cid: str, cxtime: str, param: str,
                     sig: str, sc: str) -> str:
    """signt = MD5("cxcid{cid}cxtime{t}param{param}paramToken{sig}{sc}")"""
    import hashlib as _hashlib
    raw = f"cxcid{cid}cxtime{cxtime}param{param}paramToken{sig}{sc}"
    return _hashlib.md5(raw.encode("utf-8")).hexdigest()


def compute_start_exam_sign_v2(test_user_relation_id: str, class_id: str,
                               device_cid: str, sc: str) -> Dict:
    """v2完整签名参数(对齐APP原生CLIENT_FORM_SIGN链)

    :param test_user_relation_id: 试卷页 testUserRelationId
    :param class_id: classId
    :param device_cid: 设备指纹链解出的 cid (cxcid)
    :param sc: 设备指纹链解出的 sc (签名盐)
    :return: {cxcid, cxtime, signt, signk, param, sig_raw}
    """
    cxtime = str(int(time.time() * 1000))
    param = f"startExam_{test_user_relation_id}-{class_id}"
    sig = form_sign_v2(param)
    signt = compute_signt_v2(device_cid, cxtime, param, sig, sc)
    return {
        "cxcid": device_cid,
        "cxtime": cxtime,
        "signt": signt,
        "signk": sig.replace("+", "%2B").replace("=", "%3D"),
        "param": param,
        "sig_raw": sig,
    }
