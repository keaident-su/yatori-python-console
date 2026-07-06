# -*- coding: utf-8 -*-
"""
数据库持久化对象 - 对应 Go 项目的 UserPO.go
使用 SQLAlchemy ORM 定义 User 表
"""
from sqlalchemy import Column, String, Text
from sqlalchemy.orm import declarative_base
import json

Base = declarative_base()


class UserPO(Base):
    """用户实体类 - 对应 SQLite 中的 users 表"""
    __tablename__ = "users"

    uid = Column(String(64), primary_key=True, nullable=False)        # 唯一 UID
    account_type = Column(String(32), nullable=False)                  # 账号类型
    url = Column(String(512), nullable=False, default="")              # 平台 URL
    account = Column(String(128), nullable=False)                      # 账号
    password = Column(String(256), nullable=False)                     # 密码
    user_config_json = Column(Text, nullable=False,
                              default="{}")      # 配置文件 JSON

    def user_config_turn_entity(self) -> dict:
        """用户配置信息 JSON 转字典"""
        try:
            return json.loads(self.user_config_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "uid": self.uid,
            "accountType": self.account_type,
            "url": self.url,
            "account": self.account,
            "password": self.password,
            "userConfigJson": self.user_config_json,
        }
