# -*- coding: utf-8 -*-
"""学习通数据模型 - 对应 Go 项目 xuexitong 相关结构体
完整对齐 Go CardEntity.go 中的 PointDto 系列结构体
"""
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from logic.core.models import UserCacheBase, CourseBase, Question


@dataclass
class XueXiTUserCache(UserCacheBase):
    """学习通用户缓存"""
    pre_url: str = "https://mooc1.chaoxing.com"
    is_cookie_login: bool = False
    cookie_str: str = ""
    uid: str = ""        # cookie 中的 _uid
    user_id: str = ""    # 从 courseSquareUrl 提取的 userId
    school_id: str = ""
    name: str = ""
    fid: str = ""
    vc3: str = ""


@dataclass
class XueXiTCourse(CourseBase):
    cpi: int = 0
    key: str = ""               # classId from courseSquareUrl
    course_id: str = ""
    course_name: str = ""
    teacher: str = ""
    is_start: bool = False      # content.isstart
    state: int = 0              # content.state (1=已结束)
    job_rate: float = 0.0       # 完成进度
    job_count: int = 0
    job_finish_count: int = 0
    content_id: int = 0
    chat_id: str = ""
    course_data_id: int = 0
    course_image: str = ""


@dataclass
class XueXiTChapter:
    """章节"""
    id: str = ""
    name: str = ""
    course_id: str = ""
    class_id: str = ""


@dataclass
class KnowledgeItem:
    """章节知识节点 - 对应 Go 的 KnowledgeItem"""
    id: int = 0
    name: str = ""
    label: str = ""
    index_order: int = 0
    parent_node_id: int = 0
    status: str = ""
    is_review: bool = False
    layer: int = 0
    job_count: int = 0
    begin_time: str = ""
    end_time: str = ""


@dataclass
class PointVideoDto:
    """视频/音频任务点 - 对应 Go CardEntity.go PointVideoDto"""
    card_index: int = 0
    course_id: str = ""
    class_id: str = ""
    knowledge_id: int = 0
    cpi: str = ""
    object_id: str = ""
    # SSR视图获取
    is_passed: bool = False
    fid: int = 0
    dtoken: str = ""
    play_time: int = 0      # 已播放时间(秒)
    duration: int = 0
    job_id: str = ""
    other_info: str = ""
    title: str = ""
    rt: float = 0.9
    video_face_capture_enc: str = ""
    random_capture_time: str = ""  # 大概的下次人脸时间
    att_duration_enc: str = ""
    enc: str = ""           # PageMobileChapterCard 提取的 enc
    mid: str = ""
    is_job: bool = False     # 是否为任务点
    # 类型标识
    type: str = "video"      # video / insertaudio
    is_set: bool = False
    # 视图原始数据
    attachment: Optional[Dict] = None
    # 兼容旧字段
    play_url: str = ""
    other_data: str = ""
    knowledge_id_str: str = ""  # 字符串版本用于API


@dataclass
class PointWorkDto:
    """测验/章测任务点 - 对应 Go PointWorkDto"""
    card_index: int = 0
    course_id: str = ""
    class_id: str = ""
    knowledge_id: int = 0
    cpi: str = ""
    work_id: str = ""
    school_id: str = ""
    job_id: str = ""
    puid: str = ""
    k_token: str = ""
    enc: str = ""
    is_job: bool = False
    type: str = "work"
    is_set: bool = False


@dataclass
class PointDocumentDto:
    """文档任务点 - 对应 Go PointDocumentDto"""
    card_index: int = 0
    course_id: str = ""
    class_id: str = ""
    knowledge_id: int = 0
    cpi: str = ""
    read: bool = False
    object_id: str = ""
    title: str = ""
    job_id: str = ""
    jtoken: str = ""
    is_job: bool = False
    type: str = "document"
    is_set: bool = False


@dataclass
class PointHyperlinkDto:
    """外链任务点 - 对应 Go PointHyperlinkDto"""
    card_index: int = 0
    course_id: str = ""
    class_id: str = ""
    knowledge_id: int = 0
    cpi: str = ""
    object_id: str = ""
    title: str = ""
    job_id: str = ""
    jtoken: str = ""
    link_type: int = 0
    type: str = "hyperlink"
    is_set: bool = False


@dataclass
class PointLiveDto:
    """直播任务点 - 对应 Go PointLiveDto"""
    card_index: int = 0
    course_id: str = ""
    class_id: str = ""
    knowledge_id: int = 0
    cpi: str = ""
    user_id: str = ""
    live: bool = False
    live_id: str = ""
    vdoid: str = ""
    mid: str = ""
    title: str = ""
    job_id: str = ""
    stream_name: str = ""
    live_status_str: str = ""
    live_status_code: int = 0
    video_duration: int = 0
    aid: str = ""
    module: str = ""
    is_job: bool = False
    auth_enc: str = ""
    live_drag_enc: str = ""
    live_set_enc: str = ""
    other_info: str = ""
    enc: str = ""
    live_sw_ds_enc: str = ""
    video_complete_percent: float = 0.0
    type: str = "live"
    is_set: bool = False


@dataclass
class PointBBsDto:
    """讨论任务点 - 对应 Go PointBBsDto"""
    card_index: int = 0
    course_id: str = ""
    class_id: str = ""
    knowledge_id: int = 0
    cpi: str = ""
    user_id: str = ""
    mid: str = ""
    title: str = ""
    job_id: str = ""
    module: str = ""
    is_job: bool = False
    auth_enc: str = ""
    other_info: str = ""
    enc: str = ""
    allow_view_reply: int = 0
    detail: str = ""
    reply_times: str = ""
    replay_word_num: str = ""
    end_time: str = ""
    type: str = "bbs"
    is_set: bool = False


@dataclass
class PointDto:
    """聚合DTO - 对应 Go PointDto，包含所有类型的任务点"""
    video: PointVideoDto = field(default_factory=PointVideoDto)
    work: PointWorkDto = field(default_factory=PointWorkDto)
    document: PointDocumentDto = field(default_factory=PointDocumentDto)
    hyperlink: PointHyperlinkDto = field(default_factory=PointHyperlinkDto)
    live: PointLiveDto = field(default_factory=PointLiveDto)
    bbs: PointBBsDto = field(default_factory=PointBBsDto)


@dataclass
class XueXiTWorkExam:
    """学习通作业/考试"""
    id: str = ""
    enc: str = ""
    work_id: str = ""
    course_id: str = ""
    class_id: str = ""
    knowledge_id: str = ""
    title: str = ""
    score: float = 0.0
    questions: List[Question] = field(default_factory=list)
    answer_w_id: str = ""
