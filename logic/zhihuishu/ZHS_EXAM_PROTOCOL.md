# 智慧树考试域协议文档 (ZHS_EXAM_PROTOCOL)

> 固化日期: 2026-10-13 | 来源: A方案现场抓包(热心人士资料+CDP实测)
> 模块: `logic/zhihuishu/exam_proto.py` (ZhsExamAPI)

## 一、加密体系(字节级验证)

```
secretStr = base64(AES-128-CBC(json_bytes, key, iv, PKCS7))
key = b"onbfhdyvz8x7otrp"   iv = b"1g3qqdh4jvbskb9x"
```

**请求格式(全部接口统一)**:
```
POST <base>+<path>
Content-Type: application/x-www-form-urlencoded
body: secretStr=<密文(URL编码)>&date=<毫秒时间戳>
```
- 无需RSA、无需设备签名(f分组免密; t分组=本固定key/iv加密)
- Python复刻与浏览器实测**字节级一致**

## 二、域名

| 域 | 基址 | 说明 |
|---|---|---|
| **业务(主用)** | `https://studentexam-api.zhihuishu.com/studentExam/gateway/t/v1` | 绝大多数接口在此 |
| taurus(备用) | `https://taurusexam-api.zhihuishu.com/taurusExam/gateway/t/v1` | 多数404, 少量可用 |

## 三、已验证接口(200)

| 接口 | 参数 | 返回 |
|---|---|---|
| `/exam/getCourseName` | `{recruitId}` | 课程名 |
| `/exam/getSingleRecruit` | `{recruitId}` | 课程详情(id/name/courseId/起止时间) |
| `/student/getStuProgressRule` | `{recruitId, schoolId}` | `{"makeUpStudent":"1"}` |
| `/student/getStudentHomework` | `{recruitId, courseId, type}` | 作业/章测列表(type=2已提交; next=-1=列表尾) |

## 四、JS bundle 全接口谱(54个, 从stuExamWeb.js提取)

**核心业务链**:
```
作业: /student/getStudentHomework(列表) -> /student/lookHomework(拉卷)
      -> /answer/getStuAnswerInfoNew(批阅详情) -> /answer/submit(提交)
考试: /student/getStudentFinalExam(期末列表) -> /student/doExam(进入)
      -> /answer/getStuAnswerInfoNew -> /answer/submit
章测: 同作业链(type区分)
其它: /student/getStudentOfflineExam(线下) /student/getStudentRoomExam(机房)
      /exam/getAllQuesitonAnalysis(全卷解析) /exam/getExamType(题型)
      /student/getExamToken /answer/validateSlideToken(滑块) /analysis/exceptionBackExamForPc
```

## 五、使用(ZhsExamAPI)

```python
from logic.zhihuishu.exam_proto import ZhsExamAPI
ex = ZhsExamAPI(cookie_dict)                    # cookies: {name: value}
ex.get_single_recruit("431867")                 # 课程详情
ex.get_student_homework("431867", "1000125370", hw_type=2)  # 已提交列表
ex.look_homework(**params)                      # 拉卷(参数待二次抓包定型)
ex.get_stu_answer_info_new(**params)            # 批阅详情(参数待定型)
```

## 六、定型进展(2026-10-13收官)
- [x] `/student/getStudentHomework`: **作业/章测列表 type 1/2/3/4 全通** (type=0被拒="aes异常")
- [x] `/exam/getExamType`: 通(返回题型数, 如rt=3)
- [x] `/student/lookHomework`: **结构定型 = 仅 `{"id": <int>}`**(白名单实测: 其余字段名→"传入参数异常"; 含id但值非有效作业→"aes加密参数异常"=结构已被服务端接受只差有效数据; id 取作业列表条目真实作业id)
- [x] `/student/getStudentFinalExam`: 域=studentexam定型; **无数据课程服务端NPE(平台特性)**, 非参数错
- [x] `/student/doExam`: 骨架(须 int型 id 类字段; 白名单待有数据样本)
- [ ] 考试采集链接入主流程(part.py) — 待打包轮

## 七、坑
1. **域选错必404**: getStuProgressRule在taurus域404/NPE, 在业务域200
2. **空参数=AES加密异常**: `{"recruitId":""}` 返回code=500 (页面初始化的空值无效)
3. **date字段必带**: 不带可能被拒
4. **三态判别法(2026-10-13实测总结)**: "传入参数异常"=字段名不在白名单; "aes加密参数异常(code500)"=字段名在但值有问题/缺必填; "status:-1 + NPE"=参数OK但该课程无数据(平台特性); "status:200"=成功
5. **加密触发条件**: CASLOGC cookie中的uuid存在时这些接口才走加密(协议登录天然携带)
6. **密钥加载**: 页面源码 getSecretKey→labc(11) 动态加载, 与本模块固定key字节级一致


---

## AI智课(mapCourse) 完整刷课方案 (2026-10-15 终极版)

### 完整公式(缺一不可)
1. **访问注册**: 无头浏览器(nodriver)打开 `learnPage/{courseId}/{knowledgeId}/{classId}` (纯HTTP无效,SPA壳需JS执行)
2. **视频进度**: 全部视频资源(type=1且resourcesTime>0) 逐个 `studyRecord/report` 序列(lastWatchTime递增) + `studyRecord/study` 心跳
3. **资源完成**: 全部资源(文本/视频/PPT) 逐个 `studyRecord/completed` (prog=已完成资源/总资源)

### 实测战绩 (账号16685140916)
- 医学细胞生物学: **201/201 满100%** (prog总20100)
- 中医护理学: **82/86 满100%** (98.2%, 4个超长多视频特例需多轮沉淀)
- 国家安全教育(Polymas): 35/35 全绿

### 关键接口总结
| 接口 | 用途 |
|---|---|
| `get-course-mapUid` | 课程mapUid |
| `list-knowledge-theme` | 知识树(201/86知识点) |
| `list-knowledge-resource` | 资源列表(含type/time/fileId) |
| `report_video_progress` | 视频进度(lastWatchTime) |
| `study_heartbeat` | 学习心跳(studyFileType=1) |
| `study_completed` | 资源完成(prog计算依据) |
| `record-student-page-time` | 页面时长(video-time) |

### 防刷机制
- 单轮报文学上限(~50%), 需间隔时间多轮
- 超长多视频(>2000s)需多轮时间沉淀


### 最终战绩更新 (2026-10-15 全部刷完)
- 医学细胞生物学: **201/201 = 100.0%** ✅
- 中医护理学: **86/86 = 100.0%** ✅ (4特例经多轮重刷全部推满)
- 国家安全教育(Polymas): 35/35 全绿 ✅
- **账号16685140916 智慧树全部课程彻底刷完**

### 超长多视频特例处理法
单轮仅能认部分资源(服务端限流), **重跑一轮(访问注册+全视频序列+全资源completed)即可继续累加** — 实测4特例Q2轮全数推满。
→ 项目侧: part.py._brush_ai_smart_course 已接入终极方案(重刷可用于'补刀')


---

## 批阅回读→题库更正链 (2026-10-15 live实锤, "查看回答情况"全解)

### 实证路径(用户操作→接口全链)
```
任务·作业·考试页(singleCourse/taskAndExam/{cid}/{classId})
  -> taskList(status=1) 已完成任务 -> {taskId, examId, examTestId, examPaperId}
  -> 点"成绩分" -> examDetail页(新tab, examId/examTestId/taskId参数)
  -> 点"查看答案解析" -> examloop.zhihuishu.com/exam/{et}/{cid}/{type}/{examId}?examPaperId=..
    ├─ GET getExamTestUserInfo        {examTestId, examPaperId}
    ├─ GET getAnswerSheetInformation  {examTestId, examPaperId}
    │    -> partSheetVos[].questionSheetVos[{questionId,version,correct,score,answerState}]
    │       (correct=1对/0错/null未批; 20题小练习55分构成逐题可对账)
    └─ GET getExamQuestionInfo        {examTestId,examPaperId,questionId,version}
         -> {content, questionType(Type名), result(字母,判断题不可靠), userAnswerVo,
             optionVos[{id, content, isCorrect}]}   ★正确答案=optionVos[].isCorrect==1
```

### 关键细节(踩坑实锤)
1. **域**: 全部在 `studentexamtest.zhihuishu.com/gateway/t/v1` (非 studentexam-api)
2. **形态**: GET + **仅secretStr参数(无date)**; Referer=https://examloop.zhihuishu.com/
3. **答案提取**: 统一取 optionVos[].isCorrect==1 的 content(";"连接);
   判断题选项content即"对"/"错", result字段=0不可用; 多选 result=字母(BCDE)不取
4. **kg-run-student域401根因(重要)**: ai_smart_proto._post_kr 原用模块级 httpx.post
   未携cookie→恒401; 带cookie即通(无需 xqjzxhiz 头, 该头非必需);
   另: httpx.Client.post() 不接受 verify 参数(会TypeError, 需在Client构造时传)

### 实现落点
- exam_proto.ZhsExamAPI: _get_loop/get_answer_sheet_info/get_exam_question_info_loop/harvest_review_pairs
- answer_bridge.bridge_upsert_results: 平台权威答案 upsert(新增+更正, save_many/update_many单次落盘)
- ai_smart_proto.harvest_answers: 任务级编排(未传et/ep时 taskList 自动定位)
- part.py._zhs_review_harvest_action: 刷课周期自动执行(zhs_verify_answer=1默认开, 仅AI智课, 全程只读)
- 战绩: 六腑与奇恒之腑小练习 20题全采(新增19/未变1), 入库后 lookup 抽查全对
