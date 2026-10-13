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
