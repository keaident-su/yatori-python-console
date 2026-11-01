# -*- coding: utf-8 -*-
"""题库管理控制器(方案A, 2026-10-08)

- 检索/更正内置题库缓存(questions_answers.json = local答题源缓存)
- 线程模型与 user_controller 一致: POST 读 body 后下沉线程池(避免阻塞事件循环)
- 安全: 走现有 AES-256-GCM 加密通道 + 会话令牌(与其它接口一致)
"""
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from web.service import tiku_service

router = APIRouter()


@router.get("/tiku/stats")
def tiku_stats():
    """题库概况: 总条数/文件路径"""
    return tiku_service.tiku_stats_service()


@router.post("/tiku/search")
async def tiku_search(request: Request):
    """题库检索: {keyword, page, size, searchIn(question|answer|all)}"""
    body = await request.json()
    return await run_in_threadpool(tiku_service.tiku_search_service, body)


@router.post("/tiku/update")
async def tiku_update(request: Request):
    """更正题目: {question, answer(可空), newQuestion(可空)}"""
    body = await request.json()
    return await run_in_threadpool(tiku_service.tiku_update_service, body)


@router.post("/tiku/collect")
async def tiku_collect(request: Request):
    """一键采集题目(异步任务): {uid, courseId(可空=全部课程)}

    对指定学习通账号的已提交作业回读批阅报告, 归档「题面+正确答案」
    到独立采集库(questions_collected.json)并同步更正现役库。
    2026-10-13 异步化: 立即返回, 进度用 /tiku/collect/status 轮询。
    """
    body = await request.json()
    return await run_in_threadpool(tiku_service.tiku_collect_service, body)


@router.get("/tiku/collect/status")
def tiku_collect_status():
    """查询一键采集任务状态(running/elapsed/stats/error)"""
    return tiku_service.tiku_collect_status_service()


@router.get("/tiku/examList/{uid}/{course_id}")
def tiku_exam_list(uid: str, course_id: str):
    """列出某课程的考试(供"指定考试采集"勾选, 2026-10-13)"""
    return tiku_service.tiku_exam_list_service(uid, course_id)


@router.post("/tiku/mergeCollected")
async def tiku_merge_collected(request: Request):
    """并入清洗: {mode: safe(仅新增,默认)|vote(多源投票+AI复核), maxVote}"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await run_in_threadpool(tiku_service.tiku_merge_collected_service, body)


@router.get("/tiku/mergeCollected/status")
def tiku_merge_status():
    """查询并入清洗任务状态(running/progress/stats/error)"""
    return tiku_service.tiku_merge_status_service()
