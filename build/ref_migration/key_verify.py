# -*- coding: utf-8 -*-
"""验证1: 私钥对比 + 验证2: 设备链在yatori client里跑通"""
import sys, io, base64, json, time, hashlib
out = io.open(r"build\ikun_migration\key_verify.txt", "w", encoding="utf-8")

# 1) 私钥对比
sys.path.insert(0, r"d:\yatori-go-console-main\yatori-python-console")
from logic.xuexitong.exam_sign import EMBEDDED_PRIVATE_KEY_B64
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("sap", r"d:\yatori-go-console-main\yatori-python-console\standalone_app_exam_pull.py")
sap = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(sap)

yatori_key = EMBEDDED_PRIVATE_KEY_B64.strip()
script_key = sap.FORM_SIGN_PRIV_KEY_B64.strip()
out.write("=== 私钥对比 ===\n")
out.write("yatori私钥长度: %d, 前60: %s\n" % (len(yatori_key), yatori_key[:60]))
out.write("脚本私钥长度:   %d, 前60: %s\n" % (len(script_key), script_key[:60]))
out.write("完全相同: %s\n" % (yatori_key == script_key))
if yatori_key != script_key:
    # 找差异
    for i, (a, b) in enumerate(zip(yatori_key, script_key)):
        if a != b:
            out.write("首个差异@%d: yatori='%s' 脚本='%s'\n" % (i, yatori_key[max(0,i-20):i+20], script_key[max(0,i-20):i+20]))
            break

# 2) 用pycryptodome复刻"设备链"并实测(yatori依赖)
out.write("\n=== 设备链实测(pycryptodome版) ===\n")
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import requests

# 构造设备画像
android_id = hashlib.sha256(b"test1234").hexdigest()[:16]
imei = hashlib.sha256(b"imei_test").hexdigest()[:32]
fingerprint = "Xiaomi/mi10/MI10:12/SKQ1.211006.001/1234567:user/release-keys"
duid = hashlib.sha256(("com.chaoxing.mobile:%s:%s" % (android_id, fingerprint)).encode()).hexdigest()
info = {
    "deviceUniqueId": duid, "cdid": duid, "device_id": duid,
    "android_id": android_id, "mediaDrmId": "", "oaid": "",
    "platform": "android", "os_name": "android", "os_ver": "12",
    "os_lang": "zh-CN", "brand": "Xiaomi", "board": "mi10",
    "hardware": "qcom", "model": "MI 10", "cpu_ar": "arm64-v8a",
    "app_name": "com.chaoxing.mobile", "app_ver": "7.0.4",
    "versionCode": "10995",
    "signatures": "1e27068798b6697821abbeb44a17da5483c4fb7fad7b9ce7890465ed04d0cbe0",
    "resolution": "1080*2340", "dpi": "2.75", "time_stamp": int(time.time()*1000),
}
plain = json.dumps(info, separators=(",", ":"), ensure_ascii=False).encode()
out.write("设备画像JSON: %d bytes\n" % len(plain))

# RSA分块加密(pycryptodome)
pub = RSA.import_key(base64.b64decode(sap.DEVICE_PUB_KEY_B64))
cipher = PKCS1_v1_5.new(pub)
cipher_text = b""
for off in range(0, len(plain), 117):
    cipher_text += cipher.encrypt(plain[off:off+117])
out.write("RSA加密完成: %d -> %d bytes\n" % (len(plain), len(cipher_text)))

# 实测: 登录 + 上报
s = requests.Session()
# 用脚本的UA
s.headers["User-Agent"] = sap.app_ua()
resp = s.post(sap.API_LOGIN, data={
    "fid": "-1",
    "uname": sap.aes_form_encrypt("13639031572"),
    "password": sap.aes_form_encrypt("Pjd20050611"),
    "t": "true", "forbidotherlogin": "0", "validate": "",
})
out.write("登录: %s\n" % resp.json().get("status"))
# SSO
resp = s.get(sap.API_SSO_ACCINFO)
out.write("SSO会话: result=%s\n" % resp.json().get("result"))
# 上报(pycryptodome版加密)
resp = s.post(sap.API_SSO_ACCINFO, data={"data": base64.b64encode(cipher_text).decode()})
j = resp.json()
client_id = (j.get("msg") or {}).get("clientId")
out.write("上报响应: msg有clientId=%s\n" % bool(client_id))
if client_id:
    # 解密(公钥数学运算)
    blob = base64.b64decode(client_id)
    n, e = pub.n, pub.e
    dec_out = b""
    for off in range(0, len(blob), 128):
        m = pow(int.from_bytes(blob[off:off+128], "big"), e, n).to_bytes(128, "big")
        ok = len(m) > 2 and m[0] == 0 and m[1] == 1
        out.write("  块@%d PKCS1头ok=%s\n" % (off, ok))
        if ok:
            dec_out += m[m.index(b"\x00", 2) + 1:]
    dec = json.loads(dec_out)
    out.write("★ 解密成功: cid=%s sc=%s\n" % (dec.get("cid","")[:20], dec.get("sc","")[:12]))
    out.write("★ pycryptodome版本完全可用!!! (可移植进yatori)\n")
else:
    out.write("上报失败: %s\n" % str(j)[:200])
out.close()
print("done")
