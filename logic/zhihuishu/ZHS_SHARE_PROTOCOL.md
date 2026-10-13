# 智慧树新版共享课(studyvideoh5) 协议级刷课 — 完整技术文档

> 2026-10-13 实战验证：账号 18286610553《从课堂走出来的创新》**24/24 节全绿**（UI层 pct=None + 协议层 learnTimeSec≥videoSec 双重复核通过）。
> 代码固化：`logic/zhihuishu/share_proto.py`（本目录）。

---

## 一、背景与结论（为什么必须走协议层）

| 方案 | 结果 |
|---|---|
| **浏览器播放方案**（video_brush.py / v193-v233） | ❌ 本课程不可靠：点击切换死锁 + 视频卡loading（dur=0）+ CDN/QUIC 复合问题，几天0进展 |
| **协议层直接上报**（本方案，MOGO"视频速度(倍)"同款） | ✅ **约10分钟完成 24 节**（含登录），稳定可复用 |

MOGO 参数 `视频速度(倍)`（120=秒刷、"速度超过30倍自动关闭实时进度"）印证其实现同为本方案。

## 二、完整链路（全部实测通过）

```
1. login_password(session, 账号, 密码)          # 易盾滑块纯协议自动过关 → CN31令牌
2. ShareCourseAPIClient.ensure_session()        # gologin 激活学习会话
3. video_list(rid)                              # rid=课程secret(如 4e5b...自动从学堂解析)
   └─ data.videoChapterDtos[8章].videoLessons[24节]
      每节字段: id(节id) / videoId / videoSec(时长秒) / name / isStudiedLesson
4. 逐节 prelearningNote:                        # 取学习记录主键
   pl = {ccCourseId, chapterId, isApply=1, lessonId, recruitId, videoId}
   → data.studiedLessonDto.{id, learnTimeSec}
5. 双上报:
   zwsds = base64(studiedLessonDto.id)
   ewssw = "0,1," + "2,3,...,N"                 # N = sec/5+2 (每5秒一点, 全量覆盖)
   DB版  saveDatabaseIntervalTimeV2: sdsew数组=[recruitId, lessonId, 0(smallLessonId),
        videoId, chapterId, 0(studyStatus), N(playTimes), total(学习总时长), HH:MM:SS, uuid+"zhs"]
        + payload额外带 courseId
   cache版 saveCacheIntervalTimeV2: sdsew数组=[recruitId, chapterId, ccCourseId, lessonId,
        HH:MM:SS(pos), total, videoId, 0(smallLessonId), N, uuid+"zhs"]
   (uuid = CASLOGC cookie 的 uuid 字段; total 初始=sec)
6. code=-8("学习总时长下降了") → cache层梯度补刀(见下节)
```

**加密**：`share_encrypt(payload)+dateFormate` → `secretStr`(AES-128-CBC, key/iv已还原于 api.py `_gw`)。

## 三、-8 拦截破解（关键）

**根因**：服务端对"推送值 < 当前缓存层值（历史播放累计，浏览器死磕期间被反复播放推高）"判 -8 拒绝。

**破解**：对 cache 层**梯度推送** `total = sec + [0,30,60,90,150,300,600,900,1200,2500,4000]`，直到 `code=0`：
- 常规节：`sec` 即过（16/24 立绿）
- 历史高值节：519~747 过（8节补刀）
- 极端节 1.1（反复播放累计异常高）：需 **4580** 才过

成功后再用同一 total 同步 DB 版（若 DB 单独被拒，cache 成功即已让 learnTimeSec 达标）。

## 四、复盘要点（长期维护须知）

1. **每节先 prelearningNote** 拿 `studiedLessonDto.id` —— 缺这一步上报会报"学习记录主键错误"。
2. **DB/cache 两版顺序**：先 DB 后 cache；-8 时优先攻 cache（cache 覆盖成功后 learn 通常随之上来）。
3. **会话**：`login_password` 每次会过易盾（纯协议约10秒，稳定）；cookies 可序列化复用（`cookie_jar_to_list`/`list_to_cookie_jar`+`validate_session`）。
4. **浏览器复核**（可选验收）：协议 cookies 注入浏览器（`logic/zhihuishu/` 外的 `_zhs_inject_dump.py` 思路）打开课程页读目录 pct；注意 **CDP `CookieParam` 的 `expires` 字段须省略**（传 float 会报 `'float' object has no attribute 'to_json'`）。
5. **UI 变绿口径**：章级 `learningLessonStatus/isPass`；节级 UI pct=None=完成。协议上报后 **16节立即变绿，其余在 cache 层覆盖后随即变绿**（无需等批处理）。
6. `queryStuyInfo` 接口对该账号返回 421（无权限），不影响上报链路，复核用 `prelearningNote.learnTimeSec` 即可。

## 五、使用方式

### 命令行
```bash
python -m logic.zhihuishu.share_proto --account 手机号 --password 密码 \
  --rid 4e5b5850435e4859454a58585a405a4458 --cc-course-id 1000125370 --recruit-id 431867
```

### 代码调用
```python
from logic.zhihuishu.share_proto import brush_share_protocol
stats = brush_share_protocol(cache, rid, cc_course_id, recruit_id, log=print)
# stats: {total, full, pushed, skipped, failed, elapsed, verified_full}
```

### 主流程接入（待「打包」时统一执行）
`part.py::_brush_share_course` 当前为浏览器时代的"逐秒sleep上报"慢版；
建议在打包时将该分派改为优先调用 `brush_share_protocol(cache, rid, ...)`（一行接入，失败自动回退旧逻辑）。

## 六、实战记录存档

| 阶段 | 结果 |
|---|---|
| 首轮全量（_zhs_full24） | 16/24 立即变绿；8节 -8 |
| 8节补刀（_zhs_touchup8） | 7节 DB+cache 双成功（cache 519~747 覆盖） |
| 1.2/1.1 补刀 | 1.2→652✓；1.1→4580✓ |
| **最终复核** | **UI层 24/24 pct=None；协议层 24/24 learnTimeSec≥videoSec** |

（日志：`_zhs_final_verify.txt` / `_zhs_fix12.txt` / `_zhs_fix11.txt`；脚本归档：`yatori-python-console/_zhs_tools/`（位于包目录之外、不参与打包编译，避免模块级执行脚本污染构建））
