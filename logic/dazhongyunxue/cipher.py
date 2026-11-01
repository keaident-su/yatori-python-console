# -*- coding: utf-8 -*-
"""大众云学 登录密码加密(2026-10-26 逆向实测)

来源: 登录页 login-*.js 中
    encryption: function(t){
        var e = a.enc.Utf8.parse(v.desKey);
        return a.DES.encrypt(t, e, {mode: a.mode.ECB, padding: a.pad.Pkcs7}).toString()
    }
且初始化对象中 desKey = "rememberCode"。
CryptoJS 的 DES 只取 key 前 8 字节 → 实际密钥 = b"remember"。

已验证锚点: "Lb15809938922~" -> "1mb5Pz2ku7sYxFRviDgppw==" (完全一致)
=> DES-ECB + PKCS7 + Base64, 无 IV, 确定性(同密码恒定密文)
"""
import base64
from typing import Optional

# 默认 desKey(不同局点若不同可由调用方传入)
DEFAULT_DES_KEY = "rememberCode"


def _pkcs7(data: bytes, block: int = 8) -> bytes:
    n = block - len(data) % block
    return data + bytes([n]) * n


def encrypt_password(plain: str, des_key: str = DEFAULT_DES_KEY) -> Optional[str]:
    """明文密码 -> 平台密文(base64)。失败返回 None(调用方回退浏览器登录)"""
    if plain is None:
        return None
    key8 = (str(des_key or DEFAULT_DES_KEY))[:8].ljust(8, "\0").encode("utf-8")
    data = _pkcs7(str(plain).encode("utf-8"))
    # ① pycryptodome(requirements 已声明 pycryptodome>=3.19.0)
    try:
        from Crypto.Cipher import DES
        ct = DES.new(key8, DES.MODE_ECB).encrypt(data)
        return base64.b64encode(ct).decode()
    except Exception:
        pass
    # ② cryptography 兜底(同 key 重复三次的 3DES == DES)
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        try:
            from cryptography.hazmat.decrepit.ciphers.algorithms import (
                TripleDES as _TDES)
        except Exception:
            _TDES = algorithms.TripleDES
        c = Cipher(_TDES(key8 * 3), modes.ECB())
        e = c.encryptor()
        ct = e.update(data) + e.finalize()
        return base64.b64encode(ct).decode()
    except Exception:
        return None


def self_test() -> bool:
    """锚点自检: 与真机已知密文比对(不联网)"""
    return encrypt_password("Lb15809938922~") == "1mb5Pz2ku7sYxFRviDgppw=="


if __name__ == "__main__":
    print("[self_test]", self_test())
    print("[demo]", encrypt_password("TestPwd!12345"))
