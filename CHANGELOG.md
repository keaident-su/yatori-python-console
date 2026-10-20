# 📋 更新与修复记录（Changelog）

> 本文件滚动记录 Yatori-python-console 的功能更新与问题修复（程序版本号见 `config/logo.txt`，当前为 V2.0.9.2）。
>
> **重要说明**：本程序的前端（Web 图形界面）功能因**严重问题已移除**，当前版本仅提供纯控制台模式运行；相关代码与部署文档不再随本仓库提供。

---

## V2.0.9.2 版本发布（2026-10-21，考试签名v2 + UA现代化 + 赞助面板）

### 新增与突破
- 【学习通】**考试签名 v2 攻克“最新版本 APP”强校验考试**：exam/start 需带 v2 签名链（cxcid 设备指纹链 22hex + cxtime + signt=MD5 + signk=RSA base64 + _signcode=1&_signc=1）；pull_exam_paper_api 新增 v2_material 参数（非 None 时带 cxcid/cxtime/signt/signk）；“访问异常”自动完整重走（重新 enter→滑块→fetch_exam_client_id_v2→compute_start_exam_sign_v2→v2 拉卷）；真机实证：136&198 两账号入门考试全链通过（题库命中→逐题提交→交卷→状态已完成）。
- 【学习通】UA 升级至最新真机版本 7.0.4 / 10995_342（APK 逆向实证）；考试 gate 误判修复（“人脸识别”文案误命中导致非人脸考试误跳过）。
- 【全平台】**UA 现代化防风控**：非学习通平台统一对齐 2026-10 真实桌面 Chrome 143.0.7499.192（智慧树主 API 由 Chrome100/101 升级；login_browser/ai_smart/enaea/weban 同步；青书 okhttp 4.2.2→4.12.0；TCaptcha 反爬指纹保持不动）。
- 【赞助】开局 LOGO + 全部任务完成界面加层赞助提示（`utils/sponsor.py` 金色横幅+赞助码，进程级节流每进程仅弹一次）；赞助码图片随包发布。

### 说明
- 开源剥离：web-s/WordPress 插件移出主仓（本地保留独立部署）；考试签名密钥按用户定夺保留在代码中（学习通 APP 内置签名密钥，非个人密钥）。

---

## V2.0.9.1 版本发布（2026-10-19，作业强制重做全链修复）

- 【学习通】作业强制重做全链修复：已完成状态接入重做链（原仅待批阅）、已批阅漏判修复；真机实测（汽车销售售后服务课程）闭环通过。

---

## V2.0.9 版本发布（2026-10-19，综合成绩 + 非任务点章测补做 + 前后端同步）

- 【学习通】综合成绩全链（纯协议）：`fetch_overall_score`（stat2-ans/overall-score/stu-score 全量得分率解析），进度页综合成绩块完整展示。
- 【学习通】非任务点章节测验补做（纯协议版）：数据源 GET stat2-ans/chapter-exam/s/tests/...（替换浏览器版），破译状态语义与 62/100 口径真相。
- 【前后端】PHP 插件 1.3.8→1.3.9（JS URL ?ver 升级强制浏览器刷新缓存，解决旧 JS 强缓存导致 CF_DEFS 缺字段）。

---

## V2.0.8 版本发布（2026-10-19，web 模式登录链身份 hook 补全）

- 【Web 模式】`xuexitong_activity.login()` 身份信息 hook 补全（web 启动刷课/拉课链与 CLI 一致）；修复 web 目录 gitignore 导致身份 hook 文件未入库问题。

---

## V2.0.7 版本发布（2026-10-19，身份信息体系：学校/姓名/学号全链）

- 【学习通】SSO 接口 `fetch_user_profile_api` 实测返回 schoolname/name/uname，日志+账号管理+进度页全链展示。
- 【智慧树/微伴】身份适配：智慧树 CASLOGC cookie（URL 编码 JSON 含 realName）；微伴租户学校信息。
- 【WP 前端】身份功能同步（线上版已部署）。

---

## V2.0.6 版本发布（2026-10-19，讨论/拓展阅读 + 多节点架构 + 进度页作业考试清单）

### 新增功能
- 【学习通】**拓展阅读全链**（真人阅读流程：appcd 阅读页书目列表→真实点击书目卡 extend_read）。
- 【学习通】**讨论发回复全链**（IKUN 逆向真实端点 /pc/invitation/{bbsid}/addReplys；真人 UI 流程：话题详情→replyBtn→输入框→发送）；“答题讨论”标签全套接入（cxBbsSw）。
- 【学习通】进度页作业/考试清单+待办提醒（courseDetailStat 扩展 workList/examList）。
- 【多节点架构】机器分组（group）+ 组内主备 fallback（backends 表 group_id/group_name，dbDelta 自动升级）；进度页多后端主备容错完整版（fetch_fresh_any 自动回退+connect_timeout=4s）。
- 【全平台】作业考试 generic_activity 统一分发 + 英华 activity 接入。

### 修复与优化
- 【学习通】章测答案匹配：选项前缀污染（A、/A./分值括号/HTML 实体前缀导致相似度算错）+ 多选连写拆分修复。
- 【学习通】空任务点死代码 BUG（total>=0 && total==finished 提前 continue）+ 考试任务点前置条件识别。
- 【学习通】直播任务点新版接口链破解（旧链 404 → 新链 getLiveDetail/saveTimePc/ananas liveinfo）。
- 【拟人化】考试拟人节奏全平台补齐至 6 平台（本版补齐微伴/重庆/英华/青书档位，青书答题随机思考）。
- 【打包】py_mini_racer 随包修复（beta9 遗漏导致家机日志 ModuleNotFoundError；易盾 JS/TCaptcha 失效降级浏览器）。
- 【进度页】setMeta 未定义致命修复（PHP 模板调用但从未定义导致 JS 抛错页面空白）；login connect_timeout=4s 主备切换加速。

---

## V2.0.5 版本发布（2026-10-16，正式版：全平台拟人考试 + 通用答题框架 + 学习通直播新版链）

### 新增功能
- 【学习通】**直播任务点新版接口链破解**：旧链 getLiveInfo/submitLiveProgress 皆 404 失效导致直播任务点永远跳过；新链 getLiveDetail(liveStatus=4 可回放) + saveTimePc(isStart 0→1 观看会话计时) + ananas/live/liveinfo(percentValue 进度查询，timeLong 按秒)；新链优先+旧链回退，实测进度真实增长（8.87%→25.64%→…）。
- 【学习通】**空（零任务）章节节点不再跳过**：totalcount=0 的章节仍可能内嵌视频（cards 有 iframe），原逻辑仅调 studentstudyAjax 后 continue 导致黄点永驻；修复后上报访问+继续走 node_run 解析 cards 内嵌附件；实测 83 黄点（你我职业 56 + 临床中药学 27）全部清零。
- 【全平台】**考试拟人节奏 6 平台全覆盖（0/1/2 档位）**：重庆 cq_exam_pace（整卷提交前随机停顿，按题数×档位）、微伴 wb_exam_pace（0.5s / 3+3s / 5+5s）、英华 yh_exam_pace 与青书 qs_exam_pace（作业/考试双链按档位随机），连同学习通（完整节奏引擎）与智慧树形成全平台拟人适配；WP 前端 + 生成器均同步选项。
- 【通用】**多源答题桥接与答题流程框架**：新增 `logic/core/answer_bridge.py`（全部平台统一接入 answer_engine：本地缓存→题库源→AI 按优先级调用+失败降级）与 `logic/core/qa_flow.py`（作业/考试统一骨架：题目列表→逐题多源作答→平台提交回调→交卷→题库缓存）；智慧树 `answer_bridge` 独立接入。
- 【智慧树】AI智课(mapCourse)协议客户端固化（`logic/zhihuishu/ai_smart_proto.py`）；国安教育(polymas系) SSO+待办 API 逆向入档（`scripts/zhs_guoan_ssO_notes.py`）。
- 【重庆 CQIE】纯 Python SM4-ECB 加密（`logic/cqie/sm4_pure.py`，移植自 yatori-go-core，去除 Go 端依赖）；【英华】考试/作业 HTML 解析与答案转换移植（`logic/yinghua/exam_turn.py`）。
- 【打包】**py_mini_racer 随包**：新增 mini_racer.dll(28MB)+icudtl.dat(10MB) 收集与 THIRD_PARTY 模块声明、requirements 补声明——修复 beta9 遗漏导致家机日志 ModuleNotFoundError(py_mini_racer)；易盾 JS / TCaptcha 纯协议能力开箱可用（失效时降级浏览器）。

### 说明
- 全局版本号 beta9 → 2.0.5（正式版）；Windows 单文件 exe / macOS / Linux / Docker 多架构产物与生成器、WP 控制台插件（1.3.8）同步。

---

## V2.0.4-beta8 版本发布（2026-10-13晚，AI修复 + 拟人化升级 + 协议体系扩展）

### 新增功能
- 【学习通】"增加学习次数/视频学习/阅读时长"升级为**账号级门禁**：该账号（按只刷/排除过滤后）全部课程完成前不执行，全部完成后统一执行（降低"刷完立即三指标"的节奏特征）。
- 【学习通】**人类化节奏引擎**（新模块 `logic/xuexitong/human_pace.py`，A+B+C+D）：对数正态分布+相邻题自相关（告别均匀随机）、每账号固定"行为画像"（个体习惯）、疲劳曲线+深夜时段降速、低概率"回看上一题"行为轨迹。作业/章测/考试全链路接入；模式0/1/2兼容（0=旧行为）。
- 【智慧树】协议秒刷**接入主流程**：共享课刷课自动"协议优先"（三元组全部来自课程列表响应），失败自动回退旧流程；实测24节约10秒完成+复核。
- 【智慧树】考试域协议客户端固化（`logic/zhihuishu/exam_proto.py`）：固定密钥 AES-CBC 加密的 POST 体系；已定型 getCourseName / getSingleRecruit / getStuProgressRule / getStudentHomework（作业章测列表）/ getExamType / getStudentFinalExam 骨架 / lookHomework 骨架；附 54 接口全谱与三态判别法文档。
- 【题库】三方合并超集 604752 条（本机+家机+采集库，自动备份）。

### 修复与优化
- 【AI 答题源】修复三处关键问题：①配置保存丢失 AI 类型字段（后端自动兜底继承）②"在线测试"按钮索引错位恒测本地题库 ③AI 返回非 JSON 数组（对象包裹答案）被误判失败——现全部宽松解析；端点解析防呆加固（未写协议自动补全、官方域名智能补路径）。
- 【题库】四史专项缺失题补采：685 条平台正确答案入库。

### 说明
- 本版含热心人士提供的参考资料助力。
- **前端（Web 图形界面）功能因严重问题已移除**，当前版本仅提供纯控制台模式运行。

---

---

## V2.0.4-beta6 版本发布（2026-10-13，智慧树协议秒刷 + 全系采集 + 题库体系升级）

### 新增功能
- 【智慧树】协议级秒刷全链路：登录（验证码协议自动处理）→ 课程树 → 逐节取学习记录主键 → 缓存/数据库双通道进度上报 → 自动突破"学习总时长下降"服务端限制。实战：24 节课程约 10 分钟全部完成并变绿（借助热心人士提供的参考资料完成攻克）。固化入口：`logic/zhihuishu/share_proto.py`（支持命令行/代码调用，附完整技术文档）。
- 【学习通】题库采集全模式：新增"考试采集"（进考试拉卷 → 题库+AI 作答 → 可按正确率提交 → 题目归档）、"指定考试采集"（勾选特定考试）、"采集填充"策略（现役库未命中时查询采集库，控制台可开关）。
- 【学习通】题目采集新增"考试提交正确率(%)"参数（默认 100=满分作答；低于 100 时按比例随机降级答案，降低"完美卷"特征）。
- 【题库】"一键并入现役库"新增**投票清洗模式**：冲突题逐源投票多数决 + AI 复核仲裁 + 无法判定隔离；后台异步执行+进度轮询。
- 【学习通】学习次数/学习时长上限提升至 1000 次 / 10000 分钟（原 400/4000，2.5 倍）。
- 【Web 控制台】进度大屏升级：按账号"只刷/排除课程"配置过滤显示；无任务点课程显示"当前课程无任务点"；新增人脸照片管理面板；作业/考试完成度行。

### 修复与优化
- 【Web 控制台】"加载课程列表（勾选）"按钮点击无反应（历史遗留：按钮无事件处理），已修复并可正常加载/预勾选/双向同步。
- 【Web 控制台】进度页打开等待从 15~45 秒降至 1.5~2.3 秒（新增：每 5 分钟后台预热 + 快照秒显 + 静默刷新三层机制）。
- 【题库】历史遗留错题批量修正：更正 39 条、新增 190 条（自动备份）。
- 【题库】全面体检（数据/缓存/写入/引擎/服务/前端六层）全部通过。
- 【智慧树】视频反复卡加载、弹题死循环等疑难卡点修复（点击定位、缓存/QUIC 处理经验固化）。

### 说明
- 本版含热心人士提供的参考资料助力；后端程序与 Web 控制台插件（1.3.6）配套升级。

## V2.0.4-beta5 版本发布（2026-10-12，学习通互动测验全链路）

### 新增功能
- 【学习通】"互动测验（视频弹题）自动补齐"：课程学习完成后自动拉取权威未完成清单（stat2），双接口轮换（PC/mobile 风控独立）扫描弹题 → 多源答题（本地缓存/题库/AI）→ 重登录提交 → 完成度终审。新增配置项 `cxInteractiveQuizSw`（默认开启）；配置文件生成器与 Web 控制台均已提供对应开关。
- 【Web 控制台】课程进度卡片新增"互动测验 x/y"进度显示（数据缺失自动隐藏）。
- 实战验证：5 账号 540 题（各 108/108）全部通过，零失败。

### 修复与优化
- 互动测验多选答案按"A,B,C"逗号格式提交；判断题支持"A/B"直通与文本归一化双通道。
- 答题源未命中时跳过该题（不乱答）；答对的答案自动写入本地题库缓存。

### 说明
- 互动测验与章节测验/作业/考试相互独立；开关关闭时完全不影响既有刷课流程。

## V2.0.4-beta4 版本发布（2026-10-09，答案采集归档 + 一键采集）

### 新增功能
- 【学习通】"答题后题目采集归档"：作业完成后核对平台正确答案时，顺带把「题面+正确答案」归档到独立采集库 `questions_collected.json`（与现役题库完全隔离；走既有写入机制：原子替换+每日备份+占位词拦截）。新增配置项 `cxCollectAnswers`（默认开启）；配置文件生成器与 WP 控制台均已提供开关。
- 【WP 控制台】「题库管理」页新增"一键采集题目"：选择学习通账号（可指定单课程或全部课程），后端自动遍历已提交作业回读批阅报告，归档题目并同步更正现役题库；仅"查看获取"，不做任何重做/提交。
- 后端新增接口 `POST /api/v1/tiku/collect`（任务互斥锁；仅学习通）。

### 修复与优化
- 修复"题库管理"页面因前端缓存旧版 JS 导致的"无法使用"问题（WP 插件版本 1.2.4→1.3.0，静态资源缓存参数同步升级，浏览器将自动拉取新版）。
- 配置文件生成器修复：修复 2026-10-08 版遗留的下拉组件语法错误（页面白屏），并重做「考试拟人节奏」+ 新增「答题后核对正确答案」「答题后题目采集归档」两个选项。

### 说明
- "采集归档"与"核对更正"共用同一引擎：自动（作业完成后）与手动（一键采集）行为一致。
- 章测的回读/采集链路（workAnswerId 获取）仍在验证中，本期采集覆盖"作业"。

## V2.0.4-beta3.1 版本发布（2026-10-09，作业链路二次修复）

### 重大修复：单选题"整体优先"匹配（乱序选项/碎片答案场景）

- 背景：实测——选项字母乱序的题目（作答页 id 与显示序不一致）中，缓存答案被逗号/顿号切碎后，短碎片先命中"部分文本选项"（如答案"提高客户满意度 ，避免纠纷"拆两段后先命中 A），而应按完整文本选 D，导致该题判 0。
- 修复：_match_answer_to_options 单选时先用"整串(去空白)"与选项做"相等 > 最长包含"比较，命中即返回；多选行为不变。
- 验证：真实题回归——原错误提交 A 修正为 D，重做后该题得满分；13/13 测试场景全通过。

### 修复：多空填空题 blankNum 字段格式（多空题全错根因）

- 背景：多空填空提交时 blankNum{qid} 旧值"3,"（空个数），而页面/APP 原生为"空序号串"如"1,2,3,"——服务端按后者解析，旧值导致只认最后 1 个空、该题全判 0（实测："报价/谅解/同意"仅记录了"同意"）。
- 修复：blankNum{qid} 改为"1,2,3,"序号串（与页面原生逻辑一致）。
- 验证：修复后多空题重做全部满分。

### 改进：enc_task 过期自动刷新重试

- 背景：多作业课程逐个处理耗时长，enter 阶段 enc_task 短时效可能过期（"已过时效"误报）。
- 修复：enter 遇"已过时效"时自动重新拉取作业列表刷新 enc_task 并重试一次，仍失败才跳过。

### 数据修复：题库缓存错误答案更正（依据学习通批阅报告）

- "维修作业变更服务顾问对客户作必要的…"：说明#同意#签字确认 -> 报价###谅解###同意
- "维修作业变更，修改维修工单…并更改…"：交车时间#总计价格 -> 交车时间###总维修费用
- "维修作业变更由车间主任告知服务顾问,至少提前预定完工时间…"：两小时 -> 15分钟
- "维修作业变更如果客户不同意增修…"：签字确认 -> 签免责协议

### 实测成果（源码版端到端）

- 账号 15322444327 汽车售后服务"增项处理习题-副本"经多轮修复后重做：**12/12 题全部满分（总分 100）**；另有"维修进度跟进-副本""维修确认"两作业同步用修复版重做提交（取最高成绩，无降分风险）。
- 6 个"未交"作业经查为服务端已过作答期（APP 同样不可作答，非程序问题）；"作业1"为老师设置"重做次数=0"不可重做。

---

## V2.0.4-beta3 版本发布（2026-10-09）

### 重大修复：学习通作业"选项字母识别"致命BUG（英语类课程提交假字母）

- 背景：实测事故——英语类课程（选项文本为英文）作业被提交 AVSC/HOE/STB/IFA、S/H/U 等"越界假字母"，第二次作业 37 题中 11 题必然判错，且作业"已完成"无法重做。
- 根因：_match_answer_to_options / _strip_option_prefix 把"选项文本的英文首字母"误当"选项字母"（如 'vehicle —…' 取 'V'）。
- 修复：新增 _option_letter()——仅"字母+点/顿号/冒号/括号"前缀（如"A."）才认作自带字母，其余一律按序号 chr(65+i)；精确匹配与相似度兜底在返回前均过滤 A~H 越界字母；_strip_option_prefix 同步收紧（不再剥英文选项首字母）。
- 回归：真实事故题目 11 个场景全部通过（原 HOE→ABC、AVSC→ABCD、S→A、U→B 等）。
- 覆盖：作业/章节测验/考试三条链路共用该函数，一次修复全生效；主源码与后端副本双份同步。

### 重大修复：多空填空分隔符兼容（# 与 ###）

- 根因：题库多空答案用 # 或 ### 分隔，旧逻辑只认 ###——"说明#同意#签字确认"（汽车售后服务-增项处理第7/8题）、"金属薄板壳#cover#行李箱盖#分体式结构#body panel"（英汉互译 5 空题）被整串塞进单个空导致该题全错。
- 修复：新增 _split_blank_answer()——先按 ### 拆，无效且含 # 时按 # 拆；作业填空与章节测验填空两处链路接入。

### 数据修复：题库缓存污染清洗（83 条）

- 清除 10-08/10-09 事故写入的污染记录 83 条（汽车专业英语 74 条 + 汽车售后服务"#整串"异常值 9 条），清洗前自动备份为 questions_answers.json.bak_时间戳。
- 验证：污染关键词全部 0 残留；其它课程的模糊命中关联记录 3 条经复核全部保留。

---

## V2.0.4-beta2 版本发布（2026-10-08）

### 新功能：题库缓存「在线更正」（前端「题库管理」页签）

- 后端：LocalTikuCache.update()（覆盖更正/题面重命名）+ search()（分页检索）+ 每日首改自动备份；新增接口 GET /api/v1/tiku/stats、POST /api/v1/tiku/search、POST /api/v1/tiku/update（走现有加密通道）；仅允许更正已存在的题目，沿用原子替换+外部修改检测。
- 前端（WP插件 1.2.4）：新增「题库管理」页签——关键词搜索（题目/答案/全字段）、分页浏览、在线更正（二次确认、保存后立即生效）；卡片式列表+手机端适配。
- 实测：60.2万条真实题库检索/分页/反搜/写入防护全部通过。

### 重大修复：前端"编辑已存在账号"保存后不同步（旧配置仍在跑）

- 根因：update_user_service 写库后未清理 global_var 内存 Activity 缓存（含旧User快照），startBrush 复用旧 Activity 运行（停止再启动也无效，只有重启后端才恢复）。
- 修复：update/delete/add 三处写库成功后统一 remove_user_activity(uid)，下次启动按最新库数据懒重建——编辑保存后立即生效。

### 新功能：学习通考试「拟人节奏」（防"答题节奏规律"风控）

- 背景：大号曾因每题0.2~0.5秒的机器式节奏被风控（服务端 monitorparam.duration 记录答题时长）。
- 配置：cx_exam_pace（0=关闭 / 1=标准拟人默认 / 2=谨慎更慢）。
- 节奏：开卷阅读5~15s + 每题随机思考2.5~7s（长题干/多选加成） + 每8~15题长停顿15~45s + 交卷前检查30~90s。
- 安全红线：仅时间等待，绝不模拟切屏/离开事件（纯协议零上报）。
- 推广：学习通作业/章测同款节奏。

### 改进：安全微伴日志增强

- 403/401结构化日志（异地或重复登录冲突）；-101错误码语义自动附注；完成失败详情入运行日志；Token失效附排查建议。

### 改进：全平台模式日志 + 多任务点上报

- 学习通「模式摘要」一行输出（视频模式/任务点模式/考试节奏/自动考试/自动交卷）。
- 多任务点模式（含无限制）启用时邮件/ShowDoc双通道主动推送上报。

### 改进：生成器与前端「新选项说明」

- 生成器：新增「考试拟人节奏」选项（含extra说明）+默认值。
- 前端：问号提示机制（❓点击弹说明）+手机端适配增强（弹窗自适应/16px防缩放/sticky操作栏）+关键选项tip补齐。

---

## V2.0.4-beta1 版本发布（2026-09-30）

### V2.0.4-beta1 补丁（2026-10-07）：正式考试"提交签名"逻辑突破与移植（重大）

- **背景**：继"进卷+拉题+答题"全链路打通后，正式卷的"逐题提交/交卷"被服务端拒绝（`{"msg":"提交失败：请使用学习通APP最新版本"}`）。获外部参考脚本（热心人士提供）新版（含完整提交+交卷链）后完成突破与移植。
- **提交签名完整姿势**（移植来源：热心人士提供的参考脚本，实测对照验证）：
  - **param格式**：`submitExam_{tuid}-{classId}-{enterPageTime}-{qid}-{答案值}`（四参数全拼：进入页面时间+题号+答案值）；
  - **签名链**：`sig=RSA("param"+param)`（同一把内嵌私钥）→ `signt=MD5(cxcid{cid}cxtime{cx}param{param}paramToken{sig}{sc})`；
  - **URL**：`_csign=1&_signcode=true&_signc=1&_signe=&_signk={sig}&_cxcid={cid}&_cxtime={cx}&_signt={signt}`（_signcode为字符串"true"）+ `pos=` 空 + `version=1`；
  - **form**：同时携带无下划线版 `cxcid/cxtime/signt/signk`（官方APP双签名）；Referer必须为题目页URL。
- **改动清单**：
  - `logic/xuexitong/api.py` `submit_exam_answer_api`：新增v2提交签名段（`fetch_exam_client_id_v2`→`form_sign_v2`→`compute_signt_v2`），成功时URL/form双签名；失败自动回退旧占位签名（向后兼容）。
- **进卷链路三处修复沉淀**（四史测试过程，已落地 part.py）：
  - "访问异常→iPhone UA重试"后必须恢复 mobile UA 再签名（否则iPhone UA下签名start被拒）；
  - 签名start前必须**重新过滑块**（"访问异常"重试pull会消耗validate，重试页变"安全验证不通过"）；
  - v2/v1签名成功后必须**从enc页重新解析元数据**（encRemainTime/encLastUpdateTime/testPaperId等，否则拉题缺remainTimeParam被"无权限"拒绝）。
- **实测状态（全闭环达成★）**：**13639031572-课程"108"-【没有人脸】考试：yatori 全流程跑通——进卷(v2签名) → 3题答题(言溪题库命中) → 逐题提交(全部 `{"msg":"提交成功","status":"success"}`) → 交卷(末题finalSubmitTime) → 考试变为"待批阅"——"学习通正式卷全自动考试闭环"首次完整达成！** **加码复测：19885639522 同课程同款【没有人脸】考试亦完整闭环（3题→提交→交卷→待批阅），并首次实测两个新分支：①"开考1分钟内限制提交→自动等待1分30秒后交卷"保护逻辑跑通；②跨账号本地题库缓存命中（第2题由前账号提交成功写入的缓存直接命中）。** 同名课程【拉满】(人脸卷)安全跳过（人脸准备失败→精准提示→不误伤）。四史教育（15985371026）进卷+拉题（85题）全通、提交环节待验证（用户要求停止测试）；斗罗大陆三场人脸卷被"人脸识别对比不通过"硬拦（start前置门槛）。
- **文档**：`build/ref_migration/SUBMIT_SIGN_REVERSE_LOG.md`（提交签名专项逆向记录）。

### V2.0.4-beta1 补丁（2026-10-05b）：考试人脸H5全链路逆向完成（情报层）

- **背景**：用户要求结合7.0.4逆向与参考项目继续攻坚"正式人脸监考卷"。本轮通过对服务端在线JS的完整逆向，彻底摸清了考试人脸的官方流程。
- **逆向成果（服务端JS实拉，已沉淀至 exam_sign.py 头部注释）**：
  - **全部前端签名函数及param格式**（均经 jsBridge 'CLIENT_FORM_SIGN' 交APP原生RSA签）：
    `startExam_{tuid}-{classId}`（已验证✓）、`faceCompare_{tuid}-{classId}-{currentFaceId}-{sessionId}`、`submitExam_{tuid}-{classId}-{blankNum}-{flag}`、`examSignatureCheck_...`、`keeperLog_...`；回调约定 `window[funckey](cxcid,cxtime,signk,signt,code,count,ecode)`。
  - **face-compare 完整参数集**（前端 faceCompare() 函数）：relationid/courseId/classId/currentFaceId/liveDetectionStatus/collectStatus/recogType/_provider/sessionId/SenseDetectionStatus/tk/cpi/_d；tk=cxcid_cxtime_signToken（来自原生人脸object）；带签名时追加 _signcode/_signc/_signe/signk/cxcid/cxtime/signt。
  - **人脸两套链路结论**：正式监考卷=APP原生人脸→原生拿facekey→jsBridge回传H5→带facekey直接start；face-compare仅为无APP时的降级替补（对正式卷被服务端拒绝"无效参数"，实测穷举6参数变体+4签名组合+完整参数集均拒）；自测卷（如测试7）face-compare开放，换基准法100分→全自动✓。
  - **end-to-end闭环**：to-face-compare页 processResult→facekey→CLIENT_WEB_EXTRAINFO(ENTER_EXAM)→考试页start。
- **结论**："正式人脸监考卷"的人脸凭证链必须依赖真APP原生环境（完整jsBridge+设备SDK签名），纯协议无法跨过——yatori 保持"自动识别+精准日志提示+温和跳过"的正确行为。

### V2.0.4-beta1 补丁（2026-10-05）：考试人脸认证全链路自动通过（重大突破）

- **背景**：v2签名链打通后仅剩"考前人脸"一关（服务端"人脸识别对比不通过"）。用户要求结合GitHub最新项目再挣扎一轮。
- **情报来源**：GitHub CxKitty 系列项目（face-compare 接口全网唯一参考）+ v2签名链实测移植。
- **修复底层BUG（"人脸验证失败"真正根因之一）**：`http_client.py` 的 multipart 分支只打包 data 文本字段，"files（图片）从未进 body"——所有人脸照片上传恒返回"file不能为空"（卡片人脸/考试人脸上传链路全部失效）。修复后上传 `{"result":true,"objectId":...}` 正常。
- **新增考试人脸自动认证（换基准法）**：上传人脸照 → `changefaceid` 换基准（服务端有人脸质量检测）→ `face-compare`（relationid=**taskrefId**）比对"自己vs自己"100分 → `facekey`凭证 + `faceDetectionResult`(紧凑JSON) → `start` 携带 `faceDetection=1&facekey&faceDetectionResult` → **进卷成功**。
- **端到端实测（13639031572-斗罗大陆-测试7）**：完整链路一次通过——HTTP 200 / 72977字节试卷页（含enc，remainTime计时启动）。**"人脸考试"从此可全自动**（此前只能人工APP参加）。
- **全流程验证（2026-10-05 实测）**：yatori 自动跑完"测试7"人脸考试全流程——人脸认证通过→3题全自动作答（言溪题库）→自动交卷（`{"status":"success"}`）→考试已完成；3题均写入本地题库缓存（新策略生效）。
- **补充修复（人脸拦截重试链路）**：
  - `part.py`："人脸识别对比不通过"拦截分支升级——原"直接跳过"改为"人脸准备(换基准法) → 带凭证重发start(带v2签名)"自动过人脸（已实测成功进卷）；
  - ★ 滑块 validate 是一次性消耗品：pull 那次裸 start 已用掉旧 validate，retry 必须**重新过滑块**拿新 validate（否则重试报"安全验证不通过"）——已修复。
- **改动清单**：
  - `logic/core/http_client.py`：multipart 分支补 files 字段打包（含 Content-Disposition/Content-Type/二进制安全）。
  - `logic/xuexitong/api.py`：新增 `face_compare_exam_api`（考试人脸比对）+ `prepare_exam_face`（上传#1→换基准→上传#2→比对→组装faceDetectionResult 一体化；照片源复用现有 `_face_load_image`：assets/faces/{账号}/ 目录 → 单张兼容 → 历史人脸）。
  - `logic/xuexitong/part.py`：`_exam_action` 签名段新增"考前人脸准备"——封面 `faceRecognitionCompare=1` 时自动准备凭证；v2/v1 两条签名路径的 start URL 均注入 `faceDetection/facekey/sdlkey/faceDetectionResult`；人脸被拦日志升级（区分"已带凭证仍被拦"/"未放置照片"）。
- **人脸照片**：使用现有体系（前端控制台"人脸"按钮上传 → `assets/faces/{账号}/` 多张随机轮换）；无照片时保持旧行为（跳过并提示）。
- **文档**：`build/ref_migration/FACE_BREAKTHROUGH.md`（完整链路+踩坑对照表）。

### V2.0.4-beta1 补丁（2026-10-03b）：题库缓存策略重构（提交成功后写入）

- **背景**：用户反馈"三方题库答案未写入缓存"。诊断确认真实原因：① 原"即问即存"防污染规则（选择题>20字符/含句末标点拦截）误杀大量"选项文字"型答案；② 提交失败的题也被写入（质量差）；③ 存的是"提问文本"而非"提交文本"。
- **新策略（用户方案）**：取消"即问即存"，统一改为"**提交成功后写入**"（提交成功=答案有效，彻底避免误杀/失败题污染）。
- **改动清单**：
  - `answer_engine.py`：① `query()` 移除"即问即存"块（仅留日志"答案待提交成功后写入"）；② `_answer_cacheable` 精简为只拦截"占位词/空/换行/超长(>2000)"（不再拦截">20字符/句末标点"）；③ 新增 `cache_answer_after_submit(question, answer, q_type, answer_src)` 统一写入函数（含"来源为本地缓存则跳过"去重）。
  - `part.py`：三处提交钩子统一接入——**作业**（`if submit_ok:` 行）、**考试**（`if exam_submit_ok:` 行）、**章节测验**（`if is_success:` 批量写入，循环内收集 `_ct_cache_pairs`）；写入成功时输出"已写入题库缓存(提交成功)"日志。
- **验证**：编译✓；功能测试✓（正常字母/选项文字带句号均写入成功、占位词拒绝、本地源去重跳过、文件条目数符合预期）；源码检查确认旧逻辑零残留。

### V2.0.4-beta1 补丁（2026-10-03）：考试客户端签名v2重大突破（APP原生链完整移植）

- **背景**：用户提供学习通APP原生协议实测脚本（热心人士提供），完整揭示"设备指纹链+CLIENT_FORM_SIGN签名"真实算法；yatori 完成移植并端到端验证通过。
- **新增设备指纹链**（此前完全缺失的关键环节）：
  - `exam_sign.py` 新增 `build_device_info_v2`（设备画像JSON）/ `rsa_encrypt_report_v2`（RSA-1024公钥分块加密）/ `rsa_decrypt_client_id_v2`（clientId公钥解密出 cid/sc）；
  - `api.py` 新增 `sso_accinfo_api`（SSO会话）+ `fetch_exam_client_id_v2`（完整链，结果缓存到 cache.exam_client_id/exam_sc）；
  - `models.py` XueXiTUserCache 新增 `exam_client_id`/`exam_sc` 字段。
- **新增正确签名算法**（此前30+种组合全错在消息构造）：
  - `exam_sign.py` 新增 `form_sign_v2`（RSA签"param"+param）/ `compute_signt_v2`（MD5六段链）/ `compute_start_exam_sign_v2`（一站式）；
  - `part.py _exam_action` 签名段升级为 **v2优先 + v1回退**（`_V2SignDone`异常控制跳过回退）。
- **修复滑块精度缺陷**（隐藏的第二个坑）：
  - `captcha.py` 新增 `detect_slide_offset_cv2`（cv2模板匹配，脚本同款算法），`_pass_slider_once` 优先使用；原NCC降采样差~9像素导致check失败（"安全验证不通过"）。
- **端到端实测**（斗罗大陆APTX-4869）：yatori官方流程（v2签名+修复滑块）→ 服务端响应"人脸识别对比不通过，不允许进入考试"，与实测脚本100%一致——**签名链完全打通**！4场考试均为人脸考试（faceRecognitionCompare=1），仅剩"人脸"一关（需真人脸，纯HTTP无法过）；若考试 needFaceRecognition=0 则可直接进卷全自动答题。
- **文档**：`build/ref_migration/B3_ANDROID_ATTACK_LOG.md` 新增第九章（v2突破全记录）。

### V2.0.4-beta1 补丁（2026-10-02）：学习通7.0.4逆向情报落地

- **依据**：学习通 Android 7.0.4 版（版本号10995）完整逆向工程（chaoxing_app_7.0.4/）。
- **`logic/xuexitong/exam_sign.py`**：① 头部注释更新——新增7.0.4证据链（libsecuritylib.so JNI导出 webRequestSign/verifyJsSign/cryptUserAgent/CxDevice_getDeviceInfo、rsa_util签名函数、设备链路模型）；② 新增 `message_mode=3/4`（3=参考项目模板"cxcid{v}cxtime{v}param{v}paramToken{v}"、4=带分隔符"k=v&"变体），供考试签名实测调优。
- **`logic/xuexitong/part.py`**：`_generate_device_flag` 注释增补7.0.4设备链路情报（APP真实设备码为多源画像+9项风控+服务端状态共同派生的加密值，非单一明文；本函数以APP兼容加密格式模拟生成）。
- **实测结论**：mode 0/3/4 × _signcode 0/1 组合测试（13639031572-斗罗大陆）服务端仍拒绝——证实"签名消息字节流"为服务端私有细节（业务代码在梆梆壳加密载荷内），与7.0.4逆向报告结论一致。普通考试不受影响。
- **文档**：`build/ref_migration/B3_ANDROID_ATTACK_LOG.md` 新增第八章（7.0.4逆向情报全记录）。

- **版本号升级**：`config/logo.txt`（启动横幅）、`web/server.py`、`main.py`、`build_protected.py`、Windows exe 名称（`yatori-python刷课系统V2.0.4-beta1.exe`）、Release 附件名全部同步至 **V2.0.4-beta1**。
- **本版内容（取长补短系列 · 第一批）**：
  - **【新平台支持】tsjy（超星通识教育/学习广场）课程学习**：修复"有些任务点刷不了"问题——tsjy.chaoxing.com 平台的课程在 gas/clazz 章节接口下知识节点为0会被静默跳过；新增独立学习链路（`logic/xuexitong/tsjy.py`）：Referer 鉴权 → `/plaza/course/{cid}/node-list` 拉知识点 → `/plaza/user/{cid}/{nodeId}/modify-node` 拿 h5enc → `knowledge/cards` 解析 AttachmentSetting → `POST /keeper/api/receive-studylog`（eventType=4, enc=mtEnc）上报，实测 `{"status":true}` 通过。课程拉取自动识别 tsjy 课（courseSquareUrl 含 tsjy.chaoxing.com）并分流，无需额外配置。
  - **【日志系统改造】跨天自动切换 + 账号专属日志 + uvicorn 访问日志落盘**：① 修复"系统时间过0点后仍写旧日期日志文件"的bug——自研 `_DailyRotatingHandler` 每次写入检查日期，跨天自动切换新文件（单日100MB轮转保留）；② 新增账号独立日志：刷课线程内日志自动带 `[账号|备注]` 前缀（控制台+全局文件），并同时写入 `assets/logs/accounts/{账号}_{备注}/{日期}.log`；Web 与 CLI 全平台（11个平台）自动注入账号上下文；③ uvicorn 的 HTTP 访问日志（如 `INFO: 127.0.0.1:50105 - "GET /api/v1/logTail..." 200 OK`）一条不漏写入全局日志文件；④ 新增 `/api/v1/logAccounts` 接口 + 前端"实时日志"页账号下拉（全局日志/各账号切换）。
  - **【任务点细化】微课/图书/阅读专用上报 + 投票任务点 + 任务点复核**（对齐 参考项目 取长补短）：① 新增**微课任务点**解析与专用上报接口 `/ananas/job/microCourse`（旧版归入文档报会导致任务点不识别）；② 新增**投票任务点**上报接口 `/ananas/job/vote`；③ 图书（insertbook→/ananas/job）、阅读（insertreadv2→/ananas/job/readv2）细化区分保留；④ 章节学习完成后**任务点完成度复核**（重新拉取统计，输出未完成节点数提示，对齐 参考项目 taskPointStatistics 能力，不自动无限重刷）。
  - **【积分课支持】tsjy 学习广场课积分机制打通**：查明"积分课"= tsjy 平台（学习广场）课程的游戏化积分体系——积分由看视频/阅读/测评等学习行为**自动累积**（bigdata-score.chaoxing.com/tsjy/point/*），刷课成功即积分到账；新增 `TsjyStudy.get_day_score()` 积分查询（/plaza/score/{cid}/day-score，对齐 参考项目 day-score），tsjy 课程刷完后日志自动显示"课程积分: 累计X, 今日Y"。
  - **【致命BUG修复】课程过滤（只刷/排除）匹配语义错误**：前端标签为"只刷课程(名称包含)"/"排除课程(名称包含)"，但后端 `cmp_course` 旧实现为**精确相等**（`course in course_list`）——用户按"包含"语义填写部分名称（如填"军事"想排除"军事理论(2025)"）时匹配**全部失效**：排除不生效（不想刷的课照跑）/只刷全部跳过。已修复为**包含匹配**（配置项等于课程名 或 作为子串包含于课程名 均命中），全平台（11个）过滤同步生效。已用真实账号双组实测验证（只刷组：30门→只处理1门；排除组：3门排除课全部正确跳过、其余正常学习）。
  - **【tsjy分流误判修复】混合课程回退机制**：部分课程URL挂 tsjy 但实际学习内容在标准 mooc 系统（如"四史教育-新青年·习党史": tsjy侧"课程不存在"/0节点，mooc侧147节点+59任务点）。tsjy 分流前现在会先探测节点，无节点自动**回退标准章节链路**，避免这类课被"无节点跳过"。
  - **【停止刷课空转修复】停止传播链全部补齐**（据生产日志定位：点击"停止刷课"后，当前视频虽退出，但节点线程仍继续启动后续任务点视频/文档空转 N 次）。新增停止检查点：① `_node_run` 入口（停止后不处理新节点）；② 视频/文档/章测/外链/直播/讨论/其它 全部 7 类任务点循环开头（停止后不再启动新任务点）；③ `_course_study` 入口（停止后不进入章节学习/作业/考试）；④ 课程线程启动循环（停止后不启动新课程）。
  - **【作业提交对齐网页真实格式】修复"保存成功但任务点不变绿"**：作业提交 URL 对齐学习通作业页 form 真实 action——补全 `workAnswerId/workid/cpi/jobid/knowledgeid` 参数、`ua=app`+`formType2=post`（旧实现缺参且用 ua=pc&formType=post，服务端仅暂存不关联任务点完成）。修复后服务端返回 `{"msg":"success!","stuStatus":4,"submit=true"}`（正式交卷），实测四史教育课 29 个黄点全部变绿、课程进度 50%→100%。
  - **【多选题答案残缺修复】空格分隔多答案只提交首项**：`_similarity_array_select` 的分割符不含空格——题库答案如 `'规模大 来源广 年龄跨度大'`（应为 BCD）被整句当作一个答案匹配，只匹配出单个字母（实测 `['B']`）→ 每道此类多选题都答错。已修复：标点分割失效时按空格二次分割，逐段高置信(≥0.6)匹配，四重保护（仅1段+全片段高置信+≥2字母+多于原结果才采用）防止"含空格的单一答案"被误判。验证 7/7 边界用例全过（空格三分→BCD、逗号/顿号正常、单选完整答案/单答案含空格/整句单选均不误判）。
  - **【纯图文节点黄点修复】知识点简介/推荐阅读书目不再跳过**：这类节点卡片是纯HTML文本（无iframe），`_node_run` 旧逻辑 `if not iframe_list: continue` 直接跳过——页面目录树的绿/黄由服务端"访问记录"驱动（实测这些节点 totalcount=0），因此黄点永不变绿。对齐 参考项目 修复：无iframe但desc含HTML的卡片归入其它类型（module=text_content）→ `read_point_report_api`（data-xxt ac_mark/readPoint）上报阅读记录 + `_simulated_browse` 停留30秒周期性重开卡片页。实测四史教育课 58 个图文节点全部上报成功。
  - **【夜间休息 + 积分课检测+每日积分策略】三大新功能（对齐 参考项目）**：① **夜间休息**：新增 `restSw`（开关，默认0）+ `restStart`/`restEnd`（默认23:00/06:00，可修改），开启后休息时段内刷课暂停等待到点自动继续（每15秒检查"停止刷课"可随时中断等待）；接入点：拉课后/建池后/课程循环前后。② **积分课自动检测**：新增 `jfSw`（开关，默认0），开启后启动刷课时自动扫描每门进行中课程——调 `bigdata-score.chaoxing.com/tsjy/point/getCount` 检测积分课，日志输出"🔍 检测到积分课: 今日X分（上限Y，累计Z）"。③ **每日积分策略**：检测到积分课时计算与 maxScore 的缺口，由正常刷课行为自然累积，刷课结束后 `_jf_final_report` 复查提示缺口。新增 API：`point_get_count_api`（积分数据）+ `class_weight_api`（积分考核规则）。WP插件/配置生成器已同步字段（restSw/restStart/restEnd/jfSw）。

---

## V2.0.2-beta4 版本发布（2026-09-24）

- **版本号升级**：`config/logo.txt`、`web/server.py`、`main.py`、`build_protected.py`、Windows exe 名称（`yatori-python刷课系统V2.0.2-beta4.exe`）、Release 附件名全部同步至 **V2.0.2-beta4**。
- **本版内容（beta4 修复，对应前端插件 v1.2.2）**：
  - **多任务点"双建池"重大修复**：Web 层不再按 cxNode 复制 N 份 cache（旧逻辑与引擎层重复建池 → cxNode=10 时产生 100 次登录风暴、cxNode=-1 时 `range(-1)` 为空导致不运行）；登录池建立统一由引擎层 `part._user_block` 按 cxNode 分支处理（>0 预登录池 / -1 无限制 / 0 默认3）。
  - **停止刷课不生效修复**：新增账号级停止标志（`request_stop/clear_stop/is_stopped`），在"建池前、建池循环内、课程循环、节点调度、视频轮询"5 个检查点优雅退出；停止后视频不再继续上报（修复进度回退）。
  - **前端「同时任务点数量」改回输入框**（可任意填 -1 / 0 / 正数，与配置文件生成器完全一致；插件版本升至 1.2.2）。

---

## V2.0.2-beta3 版本发布（2026-09-24）

- **版本号升级**：`config/logo.txt`（启动横幅）、`web/server.py`、`main.py`（APP_VERSION）、Windows 单文件 exe 名称（`yatori-python刷课系统V2.0.2-beta3.exe`）、Release 附件名全部同步至 **V2.0.2-beta3**。
- **本版内容（V2.0.1 之后）**：
  - **CPU 无差别适配（型号级性能配置）**：新增 `cpus/` 目录（与 main.py 同级），每颗 CPU 一份独立 YAML 配置（41 款内置：AMD/Intel 桌面+移动主流型号，下划线归一命名如 `AMD_Ryzen_7_8845HS.yaml`）；新增 `logic/core/cpu_profile.py` 负责识别（Windows 注册表 / Linux /proc/cpuinfo / macOS sysctl）+ 三级匹配（精确→别名→包含）+ 公式兜底 + 启动横幅提示。**用户新增 `cpus/{型号}.yaml` 即自动生效，无需改源码**（规范见 `cpus/README_CPU配置规范.md`）。打包时 cpus/ 自动随包复制到 exe 同级。
  - **性能策略（全局开关）**：`basicSetting.fullCpuMode`（0=默认基准核数 n-1 保留一份 / 1=全速吃满全部逻辑核）+ `basicSetting.performanceGear`（aggressive 激进[登录=基准×1.5/提交=基准/AI=基准÷2/视频=基准×¾] / conservative 稳健）。前端 WordPress 插件「后端配置」页可实时切换；配置文件生成器同步新增两个控件。
  - **运行期负载自适应**：新增 `logic/core/perf_tuner.py`——每 10s psutil 采样，CPU 负载 <50% 系数自动上调（上限 1.5×）、>85% 自动下调（下限 0.5×）；所有并发消费方（登录/提交/视频/间隔/连接池/进程池/AI 信号量）统一走 `parallel.tuned_*` 动态取值。
  - **并发全函数化改造**：`parallel.py` 由静态常量重构为动态函数（`login_workers()` / `work_concurrency()` / `ai_concurrency()` / `fast_video_workers()` / `node_start_interval()` / `cpu_pool_workers()` 等），支持热更新与全速自动缩放（配置值为 n-1 基准，全速时按 n/(n-1) 上调）；节点启动间隔下限降至 0.06s。
  - **回退早期"低配砍并发"方案**：经实测（用户反馈"明显变慢"）全面回退 IS_LOW_SPEC 减半策略，恢复原版全速 + 可选开关。

---

## 🚀 V2.0.1 版本发布（2026-09-23）

- **版本号升级**：`config/logo.txt`（启动横幅）、Web 服务版本、Windows 单文件 exe 名称（`yatori-python刷课系统V2.0.1.exe`）、Docker 镜像标签、Release 附件名（`yatori-python-console-V2.0.1`）全部同步至 **V2.0.1**。
- **本版内容（V2.0.0 之后）**：
  - **GPU 硬件加速（全厂商 / 跨平台）**：新增 `logic/core/gpu_accel.py`（NVML/nvidia-smi/WMI 惰性探测 → 评分 → 按平台给出 provider 优先级 + 解码线程建议）与 `logic/core/ort_ocr_session.py`（GPU 自适应 ONNX Runtime 会话，替换 `rapidocr_onnxruntime.utils.OrtInferSession` 注入，det/rec/cls 三个模型全部生效）。
    - 后端矩阵：**Windows → DirectML（NVIDIA/AMD/Intel/核显 全厂商）+ 有 CUDA 时优先 CUDA；macOS → CoreML；Linux → CUDA/ROCm；无可用 GPU 自动回落 CPU**。
    - 健壮性：**推理探针**（建会话成功≠真能用：缺 cuDNN 的 CUDA / 无 DX12 设备均会在 Conv 节点才报错；探针对多个候选形状零张量实跑一次，失败才换下一个后端）+ **CUDA 运行库自挂载**（自动把 pip 的 `nvidia/*/bin` 与 `CUDA_PATH/bin` 加入 DLL 搜索路径，无需系统装 CUDA Toolkit）。
    - 安装适配：`requirements.txt` Windows 改用 `onnxruntime-directml`（并注明 rapidocr 会带入 CPU 版需 force-reinstall 的技巧）；环境变量 `YATORI_OCR_CPU=1` 可强制 CPU。
    - 新增自检命令：`exe --gpu-check` / `python main.py --gpu-check`——打印显卡、平台后端优先级、可用后端与**实际生效的推理后端**；OCR 首次初始化时也会在日志/控制台输出实际后端。
    - **实测**：源码环境 det/rec/cls 全部走 CUDA（自动挂载 pip 的 cuDNN 后）；打包环境 `--gpu-check` 输出实际推理后端 **DmlExecutionProvider**；无 GPU/老显卡自动回落 CPU，功能完全不受影响。
  - **低配机性能自适应**：`logic/core/parallel.py` 新增 `IS_LOW_SPEC`（逻辑核 ≤4）判定，AI/登录/视频/解析并发与 httpx 连接池上限减半并带最小下限，节点启动间隔加倍，避免低配机上 CPU 长期高占用；高配机保持原有全速。
  - **后端配置在线读写**：新增 `web/controller/config_controller.py`——`/configGet` 读取可编辑设置（排除 web 相关项）、`/configSave` 白名单写入 config.yaml 并热更新（免重启）、`/sourceTest` 答题源真实查询测试、`/emailTest` 邮件发送测试；`web/router.py` 注册到 /api/v1。
  - **人脸本地库多张轮换**：`logic/xuexitong/api.py` 人脸加载升级——优先读取 `assets/faces/{账号}/` 目录下多张图片并随机轮换（控制台「人脸」按钮上传），降低同一张照片被风控概率；兼容旧单张 `assets/faces/{账号}.jpg`；都没有时才拉取历史人脸。
  - **HTTPS 自签证书自动生成**：`logic/launcher.py` 新增 `_ensure_self_signed_cert()`——未配置证书时调用 openssl 生成并持久化到 `assets/web_ssl/`（兼容 Windows Git 自带 openssl 路径），失败回退 HTTP。
  - **安全微伴增强**：`logic/weban/client.py` 新增 ETA 课程状态跟踪与题库解析增强。
  - **配套前端**：WordPress 控制台插件升级 1.2.0（账号字段全量补齐 / 后端配置页 / 在线测试 / 性能自适应）。
- **构建方式**：Windows 单文件 exe 与 macOS/Linux 二进制均由 `build_protected.py` 同源构建；本次沿用 Cython 编译全部自研模块为原生扩展 + PyInstaller 单文件，打包前以全量 cythonize 预检确认 0 编译不兼容。

---

## 2026-09-23

### 🎮 GPU 硬件加速真正落地（全平台自适应 + 构建来源固定 + 自检开关）

- **背景/根因**：此前“GPU 自动检测与硬件加速”只有探测、未真正生效——① `rapidocr_onnxruntime 1.2.3` 的 GPU 开关与其内部实现不匹配（`det_use_cuda` 会触发内部 KeyError、`use_dml` 被忽略），异常被吞后静默回落 CPU；② 发布包内既无 CUDA provider（为压体积裁剪）也无可用 DML 后端，OCR 恒为 CPU。
- **平台自适应后端（单一事实源）**：`logic/core/gpu_accel.py` 新增 `pick_ort_providers()`——按平台优先级（Windows: CUDA→DirectML→OpenVINO；macOS: CoreML；Linux: CUDA→ROCm→OpenVINO）与 onnxruntime 实际可用后端取交集，避免“探测到 GPU 但后端不存在”的假加速；`YATORI_OCR_CPU=1` 强制 CPU 便于对比。
- **注入 + 探针验证**：`logic/core/ocr_utils.py` 通过临时替换 rapidocr 内部 `InferenceSession` 符号，把选定后端注入其 det/rec/cls 三个会话（与 rapidocr 版本解耦，不升级依赖）；每档后端先用最小图做真实推理探针，失败自动降档——实测成功拦截“CUDA 缺 cuDNN 时会话建成功但推理崩溃”的假可用场景并逐级回落。
- **构建来源固定**：`build_protected.py` 新增 ORT 来源解析（`YATORI_ORT_SRC` 环境变量 > 解释器 site-packages > 同盘 *venv* 目录）与包内校验：Windows 构建必须内置 `DirectML.dll`，否则直接报错并给出可操作指引；杜绝此前“同一脚本两次构建收到不同 ORT、体积 151↔169↔700MB 漂移”的问题。
- **自检开关**：`main.py --gpu-check`（exe 与源码通用）输出显卡探测、平台候选后端、onnxruntime 可用后端、OCR 实际生效后端，并给出未生效原因提示。
- **实测**：① 源码 DML 环境 → 实际后端 `DmlExecutionProvider`、识别正确；② 主环境 CUDA 缺 cuDNN → 探针拦截并回落 CPU（识别仍正确）；③ 从发布 exe 完整解包实跑 → 包内后端 `DmlExecutionProvider`、识别正确；④ 打包体积 169.1MB（DirectML 增量 +18MB）。

---

## 🚀 V2.0.0 版本发布（2026-09-23）

- **版本号升级**：`config/logo.txt`（启动横幅）、Web 服务版本、Windows 单文件 exe 名称（`yatori-python刷课系统V2.0.0.exe`）、Docker 镜像标签、Release 附件名（`yatori-python-console-V2.0.0`）全部同步至 **V2.0.0**。
- **本版内容（V1.2.0 之后）**：安全微伴（WEBAN）平台接入并真机全链路验证通过；智慧树（ZHIHUISHU）平台接入（**验证中**）；内置图形界面（Web 模式，自动打开浏览器）；前后端分离部署（web-s 前端 + AES-256-GCM 加密通道）；管理界面安全加固与外网暴露面收敛；全平台课程/总进度查询（11 个平台）；SSL 证书管理（多证书 SNI 即时生效）；人脸照片上传（多张随机轮换）；Android 底座与 Docker 异形架构适配；macOS 安装与使用指南。
- **构建方式**：Windows 单文件 exe 与 macOS/Linux 二进制均由 `build_protected.py` 同源构建（内置安全微伴验证码 ONNX 模型与内置题库兜底 answer.json）；Docker 多架构镜像由 CI 按 logo.txt 版本自动打标签。

---

## 🚀 V1.2.0 版本发布（2026-09-21）

- **版本号升级**：`config/logo.txt`（启动横幅）、Web 服务版本、Windows 单文件 exe 名称（`yatori-python刷课系统V1.2.0.exe`）、Docker 镜像标签、Release 附件名（`yatori-python-console-V1.2.0`）全部同步至 **V1.2.0**。
- **本版内容**：包含下方 2026-09-21 与 2026-09-20 的全部条目——学习通作业/考试/任务点重大修复、答题链路三处修复（填空题多空/缓存防污染/视频异常重试）、推送通知按事件实时触发与通知开头自定义、学习次数/学习时长日志完善、EveryAPI 题库迁移、学习公社完整修复、多答题源体系升级、配置文件生成器 48 项提示与版本标识、跨平台适配（Windows/macOS/Linux/Docker）。
- **构建方式**：Windows 单文件 exe 与 macOS/Linux 二进制均由 `build_protected.py` 同源构建（产物输出到 `dist/`）；Docker 多架构镜像由 CI 按 logo.txt 版本自动打标签。

---

## 2026-09-22

### 🧱 安全微伴：无浏览器 / 系统限制环境的降级适配（Android 适配底座）

- **背景**：原实现中浏览器体检失败会跳过整个安全微伴账号；且验证码模块顶层强依赖 nodriver/opencv，任一缺失会导致登录（本地 OCR，无需浏览器）一起失效——在“未安装浏览器 / 系统禁止调起浏览器”及未来 Android(APK) 环境下不可用。
- **浏览器能力分级降级**：浏览器不可用时不再跳过账号——登录与课程学习照常执行（登录验证码用本地 OCR 模型）；考试环节（需无感验证码）自动跳过；个别课程完成时的点选验证码提示失败并跳过；整体日志明确说明降级原因与恢复方法（安装浏览器 / 配置浏览器路径 / CDP）。
- **验证码依赖条件化**：nodriver（浏览器）与 opencv/numpy（图形识别）改为可缺失导入（含全部注解惰性化）——无 nodriver 时登录 OCR 照常、仅浏览器验证码跳过；无 opencv 时登录环节快速失败并明确提示（不再空转重试）。
- **Android / Termux 环境识别**：新增 `_deps.is_android()`（sys.platform / ANDROID_ROOT / Termux PREFIX 三重判定）；未手动配置 browserPath/CDP 时直接判定浏览器能力不可用（避免无谓探测）；手动配置（如 Termux 连接外部调试浏览器）时仍走实测。
- **系统限制调起浏览器容错**：浏览器启动被沙箱/安全软件拦截时由实测失败触发降级；运行期验证码统一经 `browser_disabled` 开关快速跳过，不再反复尝试启动。
- **验证**：8 项降级场景测试全部通过（无 nodriver / 无 opencv / Android 探测 / Android 降级 / 桌面无浏览器降级 / 浏览器可用不降级 / client 守卫 / 登录快速失败）+ 正常路径回归通过。

### 🖥 多平台适配第二轮：Android 底座 + Docker 异形架构 + 平台画像

- **全局平台探测单一事实源**：新增 `utils/platform_info.py`（Windows/macOS/Linux/Android/Docker 判定、处理器架构名规范化、OCR/浏览器验证码/进程池能力探测、单行启动画像）；`logic/weban/_deps.is_android` 改为转发全局，消除重复实现。
- **Android(APK) 底座强化**：CPU 进程池在 Android/受限环境自动禁用改为内联执行（另支持 `YATORI_DISABLE_CPU_POOL=1` 强制禁用，排查口子）；新增 `requirements-android.txt`（Chaquopy 等打包器的依赖子集：不含 OCR/浏览器/原生 tls，对应能力自动降级）。
- **tls_client 原生库加固**：学习通滑块 TLS 指纹改为懒探测——Android/RISC-V/ppc64le/s390x 等无对应原生库的架构上，包可导入但创建 Session 时加载 so/dll 失败；现自动探测并永久降级回退 httpx 裸请求（不再反复重试）。
- **Docker 多架构条件化**：Dockerfile 按 `TARGETARCH` 自动选择依赖（amd64/arm64 完整 OCR；armv7/ppc64le/s390x/riscv64 自动切换 requirements-lite 并跳过 Chromium），支持 `--build-arg REQ_FILE=` 显式覆盖；CI 默认双架构不变，文件内附异形架构构建说明。
- **启动平台画像**：启动时打印 `[平台]`（系统/架构/(容器) + OCR/浏览器验证码/进程池能力与降级状态），多平台部署排查一目了然。
- **README**：新增「运行环境支持」矩阵（Windows / macOS 双芯片 / Linux 双架构 / Docker 双架构 / 异形架构 / Android）。
- **验证**：8 项测试全部通过（平台探测/Android 模拟/转发一致性/进程池禁用内联/tls 加固与回退/Dockerfile 断言/画像输出）+ 既有功能回归通过。

### 🍎 文档：macOS 安装与使用指南（README，小白友好逐步教程）

- **背景**：发布包提供 DMG/ZIP 两种 macOS 安装形式，但 README 缺少系统的安装使用说明（尤其未签名应用的首次打开放行），用户拿到产物后不知如何安装与运行；本次升级为“照着做”级别的详细教程。
- **指南结构（逐步式）**：
  - 第 0 步：查芯片（「关于本机」查看方法 + 分架构下载对照表，强调选错打不开）；
  - 安装前准备：config.yaml 的两种获取方式（配置文件生成器.html 的下载→填写→导出完整指引 / 手写）；
  - 方式一 DMG 六步教程：下载 → 拖进应用程式 → 首次被拦的两种情况放行（右键打开 / `xattr -cr`，含系统提示原文对照与拖拽补全技巧）→ 把 config.yaml 放进「显示包内容 → Contents/MacOS」→ 运行与看进度（日志文件路径 + 终端实时命令 + 如何提前停止）→ 卸载；
  - 方式二 ZIP 免安装两步教程：解压放配置（拖文件夹进终端、chmod、Tab 补全）→ 首次放行与实时日志；
  - FAQ 10 条：双击无反应（命令行程序属正常）、如何确认在运行、配置修改如何生效、日志位置、卸载等。
- **关键说明点**：命令行程序双击后无窗口属正常（Dock 图标表示运行中）；config.yaml 必须与可执行文件同目录（DMG 版在应用包内部）；未签名拦截属正常现象。
- **验证**：说明与程序实际行为逐项核对（打包后工作目录 = 可执行文件所在目录；`assets/`、`questions_answers.json` 在同目录自动生成）。

### ✅ 安全微伴真机实测：全链路端到端验证通过

- **实测环境**：Windows x86_64 + 本机 Chrome；6 个真实测试账号覆盖 3 所学校（贵州轻工职业大学 ×3、遵义医药高等专科学校 ×2、安阳职业技术学院 ×1）
- **通过项**（账号 202501130563 / 遵义医药高等专科学校，2025至2026年秋季安全教育项目，全流程真实执行）：
  - 登录：验证码 CNN 模型自动识别（多次均为首次识别成功）+ 学校全称自动匹配学校代码 + 账号密码登录成功
  - 浏览器检测：自动发现本机 Chrome，无感验证码能力就绪
  - 题库同步：历史试题回溯合并正常
  - 课程学习：**63/63 门必修课全部完成**（含课后习题作答、jupiter 翻页轨迹上报、视频课程按倍速对齐等待）
  - 考试：腾讯无感验证码经 Chrome 自动通过；50 题全部作答保存；**题库匹配率 100%；交卷成功，成绩 100 分**
  - 全程无异常中断，进度实时递增、ETA 自适应预估正常
- **其余账号状态矩阵**（均为账号侧状态，非程序缺陷，程序均正确识别并优雅处理）：
  - 20240314202 / 20250301244 / 20250601447（贵州轻工）：登录成功，无进行中项目（历史项目均已结束）
  - 17584370109（遵义医药）：平台返回「账号不存在」（10002）
  - 2401033503（安阳职业技术学院）：学校名不在平台 799 所列表（平台仅有「安阳师范学院」），程序正确提示核对学校全称
- **顺带修复**：登录失败提示文案去除 SDK 遗留的 config.toml 字样，改为项目配置语境

### 🖥 图形界面模式：内置网页管理界面 + 启动自动打开浏览器（桌面/手机/Docker/Android 通用）

- **背景**：普通用户无法通过命令行使用程序（macOS 双击即开终端、Android 更不可能）；原 Web 模式仅提供 API，不含任何可见界面。
- **内置管理界面**：新增 `web/static/index.html`（单文件、零外部依赖、离线可用、响应式适配手机）；包含账号卡片（平台/备注/运行状态/一键启动停止）、添加/编辑/删除、课程列表、导入 config.yaml、底部实时日志面板（SSE）；覆盖全部 11 个平台。
- **一键导入配置**：新增 `POST /api/v1/importConfig`——将程序目录 `config.yaml` 的全部账号（含 coursesCustom/备注/通知邮箱/ShowDoc/代理等完整字段）导入数据库，按（平台/URL/账号）去重。
- **配置完整注入**：界面启动刷课时自动加载 config.yaml 的 setting 段并注入多答题源引擎（`load_web_setting`），行为与控制台模式一致；修复了此前 Web 模式刷课使用默认配置、未点过“课程列表”时直接启动无反应两个缺陷。
- **启动自动打开浏览器**：Web 模式启动后自动打开 `http://127.0.0.1:<端口>/`（新增开关 `basicSetting.autoOpenBrowser`，默认开启；端口自动顺延后打开实际端口）。
- **生成器配套**：基础设置新增「Web模式(图形界面)（默认开）/ Web端口 / 自动打开浏览器」三项开关。
- **打包与路由**：build_protected.py 收集 web/static 静态资源；根路径 `/` 自动重定向至 `/web/`。
- **验证**：Chrome 实测——页面渲染/添加/删除/统计/SSE 实时日志/根重定向/importConfig 路由全部通过；Python 层 5 项单测通过；生成器页面渲染与三个新控件显示正常。

### 🌐 前后端分离架构改造：web-s 独立前端 + AES-256-GCM 通信加密 + HTTPS 支持

- **后端服务化增强**（保持兼容：webModel 未开启时行为完全不变）：
  - **通信加密通道** `web/crypto_channel.py`：AES-256-GCM 预共享密钥，请求头 `X-Yatori-Enc: 1` 触发，密文布局对齐浏览器 Web Crypto（nonce12+ct+tag），时间戳防重放，密钥自动生成并持久化（config.webSecret → assets/web_secret.txt）；
  - **HTTPS 支持**：`basicSetting.webSsl/webSslCert/webSslKey`，缺省自动生成自签证书（openssl，兼容 Windows Git 环境）；
  - **CORS 放开**（credentials=False、headers/methods 全放行）以支持宝塔等外部分离前端直连；
  - **新增 `GET /api/v1/logTail`**：日志尾部轮询接口（外部分离前端在加密通道下替代 SSE）；
  - 修复：解密失败同样以加密错误包回应防探测；中间件覆盖 Starlette 请求体缓存确保路由拿到解密数据。
- **新增独立前端 `web-s/`**（WordPress 后台风格）：
  - 纯静态单页（hash 路由，零依赖零构建）：index.html / assets/{wp.css,api.js,app.js} / config.example.js / 部署说明.md；
  - 功能：仪表盘统计、账号表格管理（增/删/改/启停/课程）、实时日志轮询、系统设置与连接测试引导；
  - **AES-256-GCM 客户端加密**（Web Crypto），与后端协议完全互通；密钥不一致时给出明确排错提示；
  - **宝塔部署友好**：上传网站根目录即用（无需伪静态/反向代理），支持宝塔 SSL 证书（配套后端 HTTPS）。
- **配置生成器**：基础设置新增「Web通信密钥」「Web服务HTTPS」两项（连同此前的 Web模式/Web端口/自动打开浏览器）。
- **验证**：后端加密往返/明文兼容/logTail/错误密钥/HTTPS 端到端全部通过；Chrome 实测前端（WP 风格渲染/加密连接/账号增删/日志轮询）通过；生成器新控件渲染正常。

### 🚀 宝塔自动化部署：WordPress 前端上线（yatori.keaident.org）

- **前端形态确定**：以「WordPress 插件」承载控制台（短代码 `[yatori_console]` + 后台菜单 + 设置页），样式作用域化 `#yatori-console-root`——完整保留 WordPress 特性并兼容任意第三方主题；插件源码归档于 `web-s/wordpress-plugin/`（含《部署与维护说明.md》）
- **全自动部署链路**（经由宝塔面板 API 的文件操作/建站/计划任务通道执行）：建站 → 部署 WordPress（中文版）→ 站点 PHP 切换为系统 PHP 8.5（修复宝塔自带 PHP 与 Ubuntu 26 系统库的二进制不兼容）→ wp-cli 安装 → 复用 `*.keaident.org` 通配符证书（有效至 2026-12-07）+ 强制 HTTPS → 插件上传激活 + 控制台页面创建 + WordPress 伪静态
- **加密联通**：插件预置后端地址 `https://1.95.49.111:8080` 与通信密钥（= config.yaml 的 webSecret），AES-256-GCM 协议与后端 crypto_channel.py 完全一致
- **验证**：首页/控制台/登录页/插件静态资源全部 HTTP 200（HTTPS 受信证书）；部署临时文件与计划任务已全部清理
- **PHP 8.2 完整修复**：宝塔 PHP 与 Ubuntu 26 系统库二进制不兼容（libxml2/libzip 符号错配）→ 为站点 PHP 8.2 配置专属兼容库（lib-compat：libxml2 2.9.4 + libzip 4）+ patchelf 注入 rpath，面板 PHP 管理（切换/重启/扩展）全部恢复正常，站点回归标准配置运行于 PHP 8.2
- **数据库登记入面板**：yatori_db 已注册至面板「数据库」页（此前用 MySQL 命令直接创建故未登记）
- **收尾**：A 记录已解析；首页/控制台/登录页公网 HTTPS 全部 200

### 🔧 WordPress 控制台全面修复（已可正常使用）

- **修复站点地址错值**：siteurl/home 曾被写成含服务器路径的错误值，导致登录跳转错乱、“Cookies blocked”、后台与控制台全部进不去 → 全库检索替换并修正
- **管理员密码重置**（新密码见交付报告；登录后可在用户设置中自行修改）
- **修复插件 JS 崩溃**（控制台显示“未连接”）：选择器作用域兜底到全局 + 模态框/提示条归一入 root（插件 v1.0.3）
- **修复 Mixed Content**：插件默认值/ WP 选项的后端地址统一为 `https://1.95.49.111:8080`
- **浏览器全链路验收**：登录 ✓ 控制台渲染 ✓ 绿灯“已连接”✓ 弹窗交互 ✓
- **永久免信任方案（正式证书上线）**：新增 `home.keaident.org → 后端` 解析，将 `*.keaident.org` 通配符正式证书（Let's Encrypt，有效至 2026-12-07）配置为后端 HTTPS 证书；WP 插件后端地址切换为 `https://home.keaident.org:8080`（插件 v1.0.4）——**任何浏览器/手机电脑无需任何信任操作，打开即连**

### 🚀 新功能：课程进度查询 + SSL 证书管理（参考 yatori-free / yatori-go-desktop 衍生项目）

- **课程+总进度查询（全平台）**：控制台“课程”按钮升级为“课程列表与总进度”——每门课展示 课程名/教师/状态/百分比/任务点完成数(x/y)/进度条
  - 覆盖 11 个平台：学习通(任务点进度)、英华、海旗、WeLearn、安全微伴(项目进度)、智慧树(目录树统计)、重庆工程、智慧职教、码上研训、青书学堂、学习公社
  - 统一数据结构 jobFinishCount/jobCount/jobRate/statusText；通用 activity 动态分发各平台 web_course_list；实测学习通 41 门课程进度完整拉取
- **SSL 证书管理（多证书并存 + 前端上传）**：参考飞牛 OS「系统设置-安全-证书」设计
  - 后端新增 `web/cert_manager.py`（SNI 按访问域名自动匹配证书）+ 证书 API（certList/certAdd/certDelete/certSetDefault/certToggle）
  - 新增/删除证书**即时生效（无需重启）**；与 config.webSslCert 兼容（作默认证书）；多一级域名访问同一后端不再告警
  - 内置界面与 WP 控制台均新增「SSL 证书」页：列表（域名/有效期/剩余天数/默认徽标）+ 上传（PEM 文本）+ 启停/删除；WP 插件 v1.0.5
  - 兼容修复：新版 uvicorn 无 Server.load 改用 config.load() 幂等预加载挂载 SNI；Python 3.13 证书解析 subject 嵌套结构适配

### 🔒 管理界面安全加固（界面+接口全保护）

- **访问认证**（web/auth.py）：口令 = webSecret（前后端通信密钥，不引入独立密码）→ 换取会话令牌（随机 32B，7 天有效，重启失效；compare_digest 校验）
- **全接口保护**：所有 /api 接口均要求 Bearer 令牌（仅 login/authCheck 白名单）；SSE 日志流支持 query token
- **隐蔽入口**：管理界面改为秘密路径（`panel_<密钥派生>`，启动日志打印），根路径与 /web/ 均伪装 404
- **登录限速**：同 IP 连续 5 次口令错误锁定 10 分钟（防爆破）
- **前端适配**：内置界面新增登录遮罩（令牌自动携带 / 401 自动重登）；WP 插件 v1.0.6 自动登录取令牌（用户无感）
- **根因修复**：launcher 密钥初始化提前到 create_app 之前（避免认证模块抢先读 web_secret.txt 导致缓存与 config 不一致）

### 🎨 站点主题：安装并启用 Sakurairo 3.0.10

- 从 GitHub 源码 zip（codeload，release 无 zip 资产时可用）部署主题至 wp-content/themes/sakurairo 并用 wp-cli 激活
- 验证：首页（Sakurairo 渲染正常）/控制台页（[yatori_console] 短代码在新主题下功能完全正常，已连接+账号列表）/登录页 均 HTTP 200；无混合内容（仅 schema.org 命名空间字串）
- 证书链复核：*.keaident.org 通配符证书（Let's Encrypt YR2）受信、TLSv1.3、有效期至 2026-12-07，服务端无异常

### 🧑 人脸上传功能 + Sakurairo 封面配置

- **人脸上传（前端嵌套）**：控制台（内置界面+WP插件 v1.0.7）账号卡片新增「人脸」按钮——可上传/预览/删除该账号的人脸照片（多张，刷课触发人脸识别时随机轮换使用）；后端新增 faceList/faceUpload/faceDelete API，存储于 assets/faces/{账号}/；_face_load_image 支持多张轮换（降低风控）
- **Sakurairo 封面配置**：外置随机图 API（经同源 PHP 代理 randbg-pc.php/randbg-mobile.php 转发，规避浏览器跨域）、多终端分离、文字LOGO“Yatori 学习工具”、两行副标题；关键：前台 iro_opt 读独立 option `iro_options`（非 theme_mods）；用户原 API(random.moejue.cn) 对服务器调用只返回教程图，当前代理指向 mwm.moe 随机图源（可随时更换）

### 🔒 后端暴露面阉割（外网彻底 404，仅保留加密 API）

- **管理界面仅限本机**：秘密入口与所有界面路径从外网访问一律 404 伪装（`_is_local` 判定 127.0.0.1/::1）；本机浏览器访问 `https://127.0.0.1:8080/panel_xxx/` 保留应急通道
- **API 强制加密+令牌**：外网请求必须携带 X-Yatori-Enc AES 加密头（明文一律 401，不泄露信息），本机豁免（内置界面便捷性）；配合原有会话令牌校验
- **暴露面体检（宝塔服务器真实外网反向）全部通过**：entry/root/web/admin 扫描全 404、明文登录/无令牌 API 全 401；WP 控制台加密正路径正常（已连接+2账号）

---

## 2026-09-21

### 🧩 新平台接入：安全微伴（WeBan）+ 智慧树（ZHIHUISHU）

- **安全微伴平台（accountType: WEBAN）**：移植自外部开源项目 AnQuanWeBan_sdk 并适配本项目架构
  - 流程：学校全称 + 账号密码/Token 登录（验证码 CNN 模型自动识别）→ 模拟官方首页 → 题库同步（历史试题回溯合并）→ 按项目交替「课程学习 + 考试」→ 最终同步
  - 验证码：登录图形验证码（OpenCV+ONNX 模型）；课程点选/考试无感验证码（nodriver 驱动本地浏览器，支持 browserPath / CDP 配置）
  - 答题：走项目多答题源引擎（题库/本地缓存/AI），SDK 自带 answer.json 作兜底，最后按配置随机/手动
  - 考试：不考/正常/追求满分/强制重考 四种模式；交卷匹配率阈值；逐题模拟等待时长
  - 课程学习：jupiter 翻页轨迹对齐官方行为、完课前按视频时长/倍速等待、行为异常(10018)自动停跑保护
  - 通知：课程/考试完成按事件实时推送（邮件+ShowDoc），并入整体汇总统计
- **智慧树平台（accountType: ZHIHUISHU）**：移植自外部开源项目 zhihuishu_sdk(fuckzhs) 并适配本项目架构
  - 流程：密码登录 → 拉取课程（Polymas AI课 + Hike共享课自动去重）→ 视频进度循环上报（每 30s 一段，速度倍率 zhsSpeed 可配）→ 完成通知
  - 非视频任务点自动标记完成；视频拉流初始化模拟（防脚本检测）；支持 includeCourses/excludeCourses 课程过滤
- **配置与前端**：配置文件生成器新增「安全微伴/智慧树」平台选择与全部配置项（含中文提示）；基础设置新增 浏览器路径/CDP地址/CDP端口（安全微伴验证码用）
- **依赖与部署**：requirements.txt 新增 nodriver / pyaes；Docker 镜像内置 Chromium；依赖缺失或浏览器不可用时仅跳过安全微伴账号，不影响其他平台
- **架构**：新增 logic/weban/ 与 logic/zhihuishu/ 模块（沿用四件套约定），launcher / global_var / web 三处注册，config 新字段向下兼容旧配置
- **验证**：26 项自动化测试全部通过（导入/注册一致性 10、mock 流程 12、集成冒烟 4）；生成器 node 语法校验 + 浏览器交互与导出实测通过；真机端到端待用户账号验证

### 💬 配置文件生成器：全量配置选项提示（48 项中文说明，降低理解门槛）

- **背景**：生成器的配置项此前仅有简短 Label（如“暴力模式倍速”“上报间隔”），新用户难以理解各选项含义与取值范围，容易配错导致运行结果不符合预期。
- **新增 48 处选项提示（输入框/开关下方的灰色小字）**，覆盖三大区域：
  - **顶部设置区（23 项）**：完成提示音、彩色日志、日志输出到文件、日志等级、图片题目OCR、通知开头名称、邮箱通知（开启/SMTP Host/SMTP Port/发件邮箱/授权码）、AI 设置（类型/AI URL/模型/API_KEY）、外挂题库地址、答题源设置（启动自检/本地缓存/缓存文件/调用顺序/答题源列表）、ShowDoc 推送（开启/推送地址）。
  - **用户账号区（25 项）**：账户类型、URL、备注名、账号、密码、通知邮箱、ShowDoc 推送与地址、视频模式、自动答题/考试模式、是否自动交卷、写章测/写作业/写考试、强制重考、设备特征码、其它任务点停留秒数、增加学习次数/时长及四项子参数（增加次数/视频观看时长/阅读时长/上报间隔）、暴力模式倍速、只刷/排除课程设定项。
  - **说明要点**：提示中标注默认值、取值范围与风险建议（如“上报间隔最低 30, 太快可能不计数”“暴力模式倍速默认 2.4”，均与程序实际边界一致）。
- **开关项提示排版优化**：将 13 个开关类选项的提示列宽由 span 2 放宽至 span 10，提示由多行竖排碎字变为单行清晰显示；仅影响渲染宽度，不影响任何配置功能与导出结果。
- **顺带修复一处潜在语法错误**：“AI URL” 文案曾含未转义半角引号，会导致生成器整个脚本解析失败（页面空白）；已改用中文引号「」并全量验证。
- **验证**：node 语法校验通过（提取内嵌脚本 `node --check` 退出码 0）；浏览器全量渲染验证 **48/48 项提示全部正确显示**（46 项常规 + 2 项条件项：AI URL 需选“其他AI”、暴力倍速需选“学习公社”）；交付截图见根目录 `生成器-配置选项提示全览.png`。

### 🧹 配置文件生成器：版本标识与旧文件归档（彻底解决“改了却找不到”问题）

- **背景**：目录中曾同时存在多个版本历史 `配置文件生成器.bak_日期.html` 备份，它们同样以 `.html` 结尾，双击后会被浏览器以旧版打开（图标与最新版一致），极易造成“功能已更新但页面找不到”的困扰。
- **最新版页面标题加入版本标识**：打开后页面顶部显示 **“Yatori-go-console配置生成器（2026-09-21 版 · 含学习时长功能）”**，一句话即可判断自己打开的是不是最新版。
- **旧版备份归档**：5 个历史备份（`.bak_20260920_*.html`）已移动到 `backup/旧版生成器备份/` 目录，并去除 `.html` 结尾（改为 `.bak`），防止误双击。
- **Go 项目同名文件改名区分**：仓库根目录 `command/` 下的 Go 项目旧版生成器已改名为 `配置文件生成器_Go项目版(与本Python项目无关).html`，避免与 Python 项目混淆。
- **结果**：本项目目录下与生成器相关的 HTML 现仅剩唯一入口 `配置文件生成器.html`（已用浏览器实测完整流程：导入 config.yaml → 展开用户 → 切换学习通 → “增加学习次数/时长”开关与 4 个输入框均正常渲染）。

### 🔔 推送通知按事件实时触发 + 通知开头可自定义 + 学习时长日志完善

**① 学习次数/学习时长日志完善（不改变行为与默认参数）**

- **学习次数（setlog）**：新增开始日志「开始增加学习次数(共N次, 每次间隔D秒, 预计耗时约E分钟)...」；结束输出「学习次数变化: X→Y次 (本次成功上报N次, 实际增加D次)」（读不到前后对比时退化为“本次成功上报N次”）；未提取到上报链接时不再静默（红字提示并继续）。
- **视频观看时长**：开始日志新增「共找到N个视频任务点」；结束输出「本次估计增加约X分钟/目标Y分钟」。
- **阅读时长**：结束输出升级为「共完成X/Y轮上报」。
- **总汇总**：开始日志新增「预计总耗时约E分钟」（次数×间隔 + 视频按1:1真实节奏 + 阅读轮数×间隔）；结束日志升级为「增加学习次数/学习时长执行完毕（学习次数+X次(目标N次)；视频观看时长约+Y分钟(目标N分钟)；阅读时长约+Z轮(目标N分钟)；总耗时约W分钟）」。

**② 推送/通知按事件实时触发（整体通知保留并升级为汇总）**

- **新增按事件通知**（邮件 + ShowDoc 双通道，与整体通知共用发送函数，发送串行化保证线程安全，不播放提示音）：
  - **课程完成** → 「课程【X】已完成」（课程学习完毕时即时发送）；
  - **作业完成**（仅本次实际提交成功的作业）→ 「课程【X】-作业【Y】已完成提交（状态：待批阅——等待老师批阅；若已自动批阅请以学习通页面为准）」；未自动交卷模式则为「已完成作答（未自动交卷模式，答案已保存）」；
  - **考试完成**（仅本次实际交卷成功的考试）→ 「课程【X】-考试【Y】已完成（成绩：N分）」或「（已交卷；若含主观题将处于待批阅——等待老师批阅，成绩可在学习通查看）」（成绩从交卷响应中尽力解析，有则带上）。
- **历史已完成项不重复通知**（按用户选择）：仅本次运行实际完成的作业/考试才发送通知；跳过类的历史状态（待批阅/已批阅/过期等）沿用原日志提示，不产生重复通知。
- **整体通知保留并升级为汇总**：全部课程跑完后仍发送一条整体通知，内容升级为「通知：所有课程已执行完毕（本次完成：课程X个、作业Y个、考试Z个）」（无统计时保持原文案）；双通道开关与完成提示音行为不变。

**③ 通知开头名称自定义（默认 Yatori）**

- 新增配置 `setting.basicSetting.noticePrefix`（默认 “Yatori”；留空自动回退默认；超长自动截断至30字符）；应用于邮件发件人名/主题/HTML标题 与 ShowDoc 推送标题（如填“小明”则标题为“小明课程助手通知”）。
- **配置文件生成器同步**：基础设置区新增「通知开头名称」输入框（默认值 Yatori）；旧配置文件无该字段时自动使用默认值，向后兼容。

**验证**：23 项冒烟用例全部通过（默认值/空值回退/超长截断/camelCase与snake_case兼容/双通道发送/通道开关隔离/汇总文案/无统计回退/事件点挂接）；真实 config.yaml 加载回归通过；生成器 node 语法校验 + 浏览器渲染验证通过；全平台模块导入回归通过。

### 🧹 答题链路三处修复：填空题多空 / 题库缓存防污染 / 视频异常重试

**① 填空题多空答案（修复提交空/`<MISSING>`）**

- **根因**：题库对多空填空题用 `###` 分隔答案（如 `4###2`），旧逻辑把整串填入第 1 空（作业）/所有空（章测），且作业侧只声明 1 个空位；提交调试日志因按 `answer{qid}` 精确查找而显示 `<MISSING>`（误导）。
- **修复**：作业侧按 `###` 拆分 → 逐空生成 `answer{qid}1..N` + `blankNum{qid}=N,`；章测侧按空序号将拆分值依次填入页面 `answer{qid}{i}` 字段（越界取最后一空、单答案保持“所有空同填”原行为）；提交调试日志改为汇总展示各空提交值（不再误显 MISSING）。

**② 本地题库缓存防污染（防止错误长文被缓存并命中）**

- **根因**：第三方题库/AI 偶发返回整段错误文本（案例：多选题返回一整段文章），旧逻辑无条件回写本地缓存，后续查询直接命中脏答案，污染答题正确率。
- **修复**：新增纯函数 `_answer_cacheable(ans, q_type)`（logic/core/answer_engine.py）——选择题/判断题答案 >20 字或含句末标点（。；;!?!）判为脏数据拒绝写入；其它题型仅拦截 >500 字或含换行的恶劣数据；拦截时输出明确日志「本次未写入(答案疑似异常数据, 已拦截防污染)」。

**③ 视频提交异常页重试（HTML/非 JSON 返回）**

- **根因**：服务端偶发返回 HTML 错误页（非 JSON），旧逻辑直接放弃该视频。
- **修复**：解析失败时按原状态（同一 playingTime/isdrag）自动重试一次，仍失败才放弃并打印「视频提交返回异常(已重试1次)」。

**验证**：28 项冒烟用例全部通过（拆分边界 '4###2'/三空/空尾/越界/无后缀字段、缓存过滤 14 例、三处静态检查、config.yaml 与模块导入回归）。

### 🔧 学习通：作业 / 考试 / 任务点重大修复（已实测验证）

**作业（修复"开关已开启但作业未完成"）**

- **修复选项解析失效**：学习通新版作业页选项节点变为 `<div id="A" class="centerSpan workWrap">`（属性顺序颠倒、class 多值化），旧解析规则无法匹配 → 选项数组为空 → 单选/多选全部蒙"A"。现已按"开标签含 centerSpan 即识别 + 从标签单独提取选项字母"兼容新旧页面结构。
- **修复提交字段缺失**：新版页面关键字段 `answerId` / `workRelationAnswerId` 位于题目页（enter 页不再提供），旧逻辑提交时携带空字段。现已三级兜底补全（testUserRelationId → answerId → workRelationAnswerId），并在首题拉取后回填供翻页使用。
- **修复「翻页失效」重大缺陷（提交成功但大量题目空白）**：拉题 URL 中多余携带的 `oldWorkId / msgId / checkIntegrity` 参数会导致服务器**忽略翻页参数 index**——每次拉题都固定返回第 1 题，最终造成"作业提交成功但只有第 1 题有答案、其余全部空白"。现完全对齐 Go 原版的最小参数 URL + 手机客户端 UA（MI 5X），实测连续翻页 5/5 全部正确；并新增**题目去重防污染保护**——若翻页异常（拉到重复题目）先重试，仍失败则中止本作业且不做整卷提交，杜绝把同一题答案重复提交的污染。
- **修复「无效的作答记录」**：仅用精简 URL 拉题会跳过"建立作答记录"步骤，导致提交被服务器拒绝（msg：无效的作答记录）。现完全复刻真实浏览器流程：进入作业时先用**完整版 URL**（对应页面"开始/继续答题"按钮 jump()，含 oldWorkId/msgId/checkIntegrity/keyboardDisplayRequiresUserAction）激活作答记录，之后再用精简 URL + index 逐题翻页；同时提交侧同样加入题目去重保护。
- **实测（真实账号端到端）**：《创新创业教育》全部 10 个作业（158+ 题）逐一拉题、独立作答、真实提交成功，**0 次翻页异常、0 次提交失败**，重新拉取列表 10/10 全部变为「已完成」；《中华优秀传统文化》4 个作业（14 题）全部提交成功。

**章测（修复「作业提交失败」）**

- **修复判断题渲染陷阱**：学习通有时将判断题渲染为显示文本“【单选题】”，但真实题型藏在页面结构（`answerList panduan` 与隐藏域 `answertype=3`）中。原解析仅看显示文本→判断题被误判为单选→选项为空→答案原样提交（如“错”）→服务器返回“作业提交失败！”。现已改为**三层判定**（panduan 结构 > 隐藏域 answertype > 显示文本），判断题正确识别并转为 `true/false` 提交（兼容“对/错/√/×/T/F/A/B”等写法）。
- **实测**：【信息技术与大数据】用户日志中 5 个“作业提交失败”的章测（菜单和工具栏/文件和文件夹的查找/程序设置和任务管理器/文件和文件夹简介/域名与域名解析）**全部重新提交成功**（`success! stuStatus:4`）；另回归测试新账号《贵州省情》2 个含单选/多选/简答混合题型的章测均正常提交成功（0 回归）。

**文档 / PPT / PDF / 图文任务点（修复"处理完成但不变绿"）**

- **根因修复**：学习通文档附件**没有 `job` 字段**（仅 work 附件才有），旧逻辑按"字段缺失 = 非任务点"处理，导致**所有文档类任务点被静默跳过**。现改为"能匹配到即视为任务点，job 显式给出时才以它为准"。
- **修复「无效的请求参数」（二次修复）**：普通参考文档（无附件顶层 `jobid`、仅 `property._jobid`）本不是任务点，旧逻辑用 objectid 误匹配后强行上报，被服务器拒绝（msg：无效的请求参数）。现完全对齐页面 `documentJob.js` 的 `isJob()` 判定：**只有附件顶层 `jobid` 存在的文档才视为任务点并上报**；非任务点文档（子网掩码.pptx / 顶级域名.docx / 核外电子排布.pdf 等）正确跳过，不再报错。
- **实测**：新账号《贵州省情》全部 54 个真任务点文档（含省情绪论.pptx 等）上报后均输出「文档阅览状态：True」，6 个非任务点文档正确跳过；旧账号《走进大学化学》《信息技术与大数据》的 40+ 个非任务点文档全部不再误报。
- **新增阅读行为上报**（ac_mark / readPoint，对齐 Go 原版 ReadSubmitTimeLog）：上报阅读字数与滚动高度，模拟真实滑动阅读，辅助服务端判定任务点完成。
- **实测**：PPT《省情绪论.pptx》上报成功（文档阅览状态 True）、阅读行为上报成功、课程进度 0/366 → 1/366（页面变绿生效）。

**空任务点 / 停留行为（不再单纯 sleep）**

- 新增「模拟浏览」机制：空任务点及其它类型任务点处理期间，**周期性重新打开任务点页面**（模拟点击 / 反复进入），并在中途与结尾上报阅读行为（模拟滑动到底部）；空任务点停留时间**强制不低于 30 秒**。

**考试（异常状态明确告知）**

- 新增明确日志：考试已过期 / 已截止（无法参加，已跳过）。
- 新增明确日志：考试要求人脸识别（服务器人脸比对未通过，纯 HTTP 无法完成考前人脸认证）。
- 新增明确日志：拉题被服务器拒绝（需人脸识别 / 客户端签名或入口校验未通过）。
- 优化提示：需手机 APP 客户端签名时，日志提示 deviceFlag 配置方法。
- 章测已过截止时间：明确告知「该章测已过截止时间且未批阅，无法作答，已自动跳过」。
- 考试同样新增题目去重保护（翻页异常时中止且不交卷，避免重复提交）。

**「已完成但显示待批阅」提示（新增）**

- 已做完但仍显示"待批阅"的任务点（**章测 / 作业 / 考试**）现在都会输出明确提示，告知"已提交、等待老师批阅，无需重复操作"：
  - 章测：拉取章测页面自动识别状态，区分输出「已完成提交（待批阅）/ 已批阅 / 已过截止时间」文案；
  - 作业：列表状态为"待批阅/已批阅"时输出「该作业已完成提交（状态：待批阅），无需重复操作，已跳过」；
  - 考试：状态为"待批阅/已批阅"时同样输出明确文案；
  - 已完成的测验类节点被跳过时，也会标注「如页面显示"待批阅"，表示已提交、等待批阅，无需重复操作」；课程任务点全部完成时同步给出该说明。

### 🔌 答题源：EveryAPI 题库迁移新域名

- **接口迁移**：`go.every-api.com`（官方已停用）→ `https://q.icodef.com/api/v1/q/{问题}`；配置中填写旧地址会自动纠正。
- **查询机制调整**：简单模式优先（`simple=true&split=#`，直接返回以 `#` 拼接的答案串）→ 结构化模式兜底；移除已失效的 AI 聊天兜底。
- **适配服务端限流**（"2并发限制"）：客户端全局串行 + 最小请求间隔 + 限流退避重试。
- 修复阅读行为上报接口因缺少 `httpx` 导入导致的静默失败。

### 📈 学习通「增加学习次数/学习时长」升级为 yatori-free 三指标设计

- **对齐 yatori-free 三指标**（每账号独立设置）：学习次数 `addStudyCount` / 视频观看时长 `addStudyVideoMinutes`（分钟）/ 阅读时长 `addStudyReadMinutes`（分钟）；
- **默认值对齐 yatori-free**：三项默认均为 **0 = 不增加**（未设置时不做任何操作）；上限对齐其界面限制（次数 ≤ 400，时长 ≤ 4000 分钟，超限自动修正）；
- **视频观看时长**（参照 chaoxing_tool set_time）：对课程视频任务点做播放进度上报（从当前进度逐分钟上报至视频结束）；**实测发现快报不被服务器计入，必须按真实播放节奏（约 58 秒/分钟）执行**；
- **阅读时长**：对课程阅读类任务点循环进行阅读行为上报（ac_mark/readPoint），仅课程含阅读类任务点时生效；
- **实测验证**（新账号贵州省情 14%）：视频播放上报后服务器**实时保存进度**（play_time 0→565s）并将对应任务点**标记完成**（课程进度 14%→15%，54/366→55/366）；学习次数 setlog 机制此前已验证（1 次访问=次数+1）；
- 配置文件生成器（学习通账号区域）同步新增“视频观看时长/阅读时长”两个输入框，默认数据同步更新；README 第 8 节已更新。

---

## 2026-09-20

### 🏫 学习公社（ENAEA）完整修复与增强（已实测验证）

- **修复登录完全不可用**：① 模块底部一段重复占位代码将正式登录实现覆盖为"登录功能待实现"；② 接口域名与路径全部错误（`study.enaea.cn` 域名不存在）。已按官方核心库全量重写：
  - 登录改用 `passport.enaea.edu.cn`（密码 MD5 大写加密），ASUSS 会话凭证；
  - 学习站域名纠正为 `study.enaea.edu.cn`，项目 / 课程 / 视频 / 学时提交接口全部对齐官方实现（含 SCFUCKP 凭证与 icourse 外部课程支持）。
- **新增暴力模式倍速配置** `bruteSpeed`（最低 2.4 / 未填写默认 2.4）。经实测：服务端对单次提交封顶 5 分钟、提交间隔小于 25 秒会被拒绝，**有效倍速上限为 12x**——设置大于 12 时自动按 12x 执行并在日志中说明。
- 单账号登录失败不再终止整个程序，改为记录原因并跳过，不影响其他账号。

### 📖 学习通：新增「增加学习次数/学习时长」功能（setlog 机制）

- 参照 yatori-free / chaoxing_tool 实现：课程**全部任务点完成后**，按配置间隔访问学习记录上报链接，累计学习次数与学习时长；执行前后自动读取并展示当前学习次数。
- 配置项（每个账号独立配置）：`addStudySw`（开关）/ `addStudyCount`（次数）/ `addStudyDelay`（间隔秒，强制 ≥30）；配置文件生成器同步支持。

### 🎯 多答题源体系升级

- **新增题库接入**：N1 题库（`n1`）、ZE 题库（`ze`）、EveryAPI 题库（`every`）——均支持启动自检、失败自动回退、本地缓存回写，配置文件生成器类型下拉同步更新。
- **修复 AVXE 题库超时**：接口域名已迁移至 `tk.wanjuantiku.com`（旧地址自动纠正，原"read operation timed out"根因是配置了文档站地址）。
- **本地题库缓存升级为独立答题源**（`type: local`）：可单独开关、参与 `order` 排序、外部题库答对后自动回写并输出日志。
- **全量日志体系**：本地缓存与每个答题源在每一次被尝试调用时（成功 / 无结果 / 异常 / 被禁用 / 被跳过）均输出日志；答题与提交日志明确标注命中的答题源及所属课程 / 章节。

### 💻 跨平台适配（Windows / macOS Intel+ARM / Linux / Docker）

- **Intel Mac 依赖钉扎**：onnxruntime 1.24+ 已停止发布 macOS x86_64 轮子，`requirements.txt` 自动为 Intel Mac 安装 1.23.2，其余平台跟随最新版。
- 新增 `requirements-lite.txt`：供无完整轮子支持的异形架构（armv7 / RISC-V / LoongArch 等）使用（自动禁用本地 OCR，其余功能不受影响）。
- **Docker 增强**：预装 libgomp1 / libgl1 / libglib2.0-0 / tzdata，统一 UTF-8 环境变量；多架构镜像（linux/amd64 + linux/arm64）自动构建分发。
- **Windows 重定向输出加固**：控制台编码不支持的生僻字符自动替换，不再导致打印崩溃。

---

## 更早的主要更新（摘要）

| 日期 | 内容 |
|------|------|
| 2026-09-16 前后 | 多答题源引擎上线（言溪 / AVXE / AI 顺序调用、失败自动回退、启动自检）；答题与提交日志标注命中答题源 |
| 2026-09 上旬 | 学习通设备特征码（deviceFlag）动态生成与考试签名支持；图片题本地 OCR 识别；非标准任务点支持；配置文件生成器多项增强 |
| 2026-09 初 | 多核并行优化（多任务点 / 多课程并发）；本地题库缓存防覆盖保护与性能优化；ShowDoc / 邮件双通道推送 |

> 早期详细变更可参考项目提交历史与 README「作者有话说」章节。
