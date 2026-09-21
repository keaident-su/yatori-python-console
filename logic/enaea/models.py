# -*- coding: utf-8 -*-
"""
学习公社数据模型 (对齐 yatori-go-core: api/enaea/EnaeaApi.go + aggregation/enaea)
"""
from dataclasses import dataclass, field
from typing import List, Optional

from logic.core.models import UserCacheBase, CourseBase

# 学习公社正确域名(注意: 不是 enaea.cn, 该域名不存在)
ENAEA_STUDY_URL = "https://study.enaea.edu.cn"
ENAEA_PASSPORT_URL = "https://passport.enaea.edu.cn"


@dataclass
class EnaeaUserCache(UserCacheBase):
    """学习公社用户缓存"""
    pre_url: str = ENAEA_STUDY_URL
    passport_url: str = ENAEA_PASSPORT_URL
    asuss: str = ""            # 登录凭证 cookie
    scfuckp_key: str = ""      # 视频统计接口下发的 SCFUCKP* cookie 名
    scfuckp_value: str = ""    # 对应 cookie 值
    circle_id: str = ""        # 当前项目ID


@dataclass
class EnaeaProject:
    """学习公社项目(期数)"""
    circle_id: str = ""
    circle_name: str = ""
    cluster_name: str = ""
    start_end_time: str = ""


@dataclass
class EnaeaCourse:
    """学习公社课程(侧边栏条目)"""
    title_tag: str = ""            # 侧边栏标签(如"课程学习"/"选修")
    course_title: str = ""         # 课程名称
    remark: str = ""               # 课程备注名
    course_id: str = ""
    circle_id: str = ""
    syllabus_id: str = ""
    study_progress: float = 0.0
    course_content_type: str = ""  # video / external_link
    course_external_type: str = ""  # icourse 等
    course_content_link: str = ""


@dataclass
class EnaeaVideo:
    """学习公社视频节点"""
    id: str = ""                   # 节点ID(submitStudyTime 的 id)
    title_tag: str = ""            # 侧边栏标签
    course_name: str = ""          # 课程名称(remark)
    course_content_str: str = ""   # 视频标题
    file_name: str = ""
    study_progress: float = 0.0
    course_id: str = ""
    circle_id: str = ""
    video_length: int = 0          # 视频时长(秒)
    scfuckp_key: str = ""
    scfuckp_value: str = ""
