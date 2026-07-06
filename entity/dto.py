# -*- coding: utf-8 -*-
"""
数据传输对象 - 对应 Go 项目的 entity/dto/
"""
from dataclasses import dataclass


@dataclass
class UserDTO:
    """用户数据传输对象"""
    uid: str = ""
    account_type: str = ""
    url: str = ""
    account: str = ""
    password: str = ""
    remark_name: str = ""
    is_running: bool = False
