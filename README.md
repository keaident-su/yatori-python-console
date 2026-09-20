# Yatori-Python-Console

> 本项目是借助 AI 基于 [yatori-go-console](https://github.com/yatori-dev/yatori-go-console) 重构的 **Python 版本** 多平台网课自动刷课工具。
>
> 独立程序、不依赖浏览器，支持多账号并行、多任务点并发刷课。
>
> **当前版本：V1.1.0**

## 📢 作者有话说

我也是用 AI 协助重构的，学习通测试通过了，其他的没试过。

## 🚀 快速开始

### 环境要求

- Python 3.13+

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

在项目根目录创建 `config.yaml` 配置文件（该文件已加入 `.gitignore`，不会上传到仓库）：

- **方式一**：直接打开 `配置文件生成器.html`，在浏览器中可视化生成 `config.yaml`
- **方式二**：参考 `config/config.yaml` 模板手动编写（详见下方「详细使用方法」）

### 启动

```bash
python main.py
```

## 📖 详细使用方法

### 1. 配置文件结构

```yaml
setting:                          # 全局设置
  basicSetting:                   # 基础设置
    completionTone: 1             # 刷完提示音：0关闭 / 1开启
    colorLog: 1                   # 彩色日志：0关闭 / 1开启
    logOutFileSw: 1               # 输出日志文件：0关闭 / 1开启
    logLevel: 'INFO'              # 日志等级：DEBUG / INFO / WARNING / ERROR
    logModel: 0                   # 日志模式
    webModel: 0                   # Web模式：0关闭 / 1启动 FastAPI Web 服务(默认端口8080)
    webPort: 8080                 # Web服务监听端口(程序支持多开, 端口被占用会自动顺延到空闲端口)
  emailInform:                    # 邮箱通知（可选）
    sw: true                      # 总开关
    SMTPHost: 'smtp.example.com'
    SMTPPort: '465'
    userName: 'your@email.com'
    password: 'your_password'
  aiSetting:                      # AI 答题设置（autoExam=1 时必填）
    aiType: 'DEEPSEEK'            # 见下方「AI 类型对照表」
    aiUrl: ''                     # aiType=OTHER 时填自定义接口地址
    model: 'deepseek-chat'        # 留空则使用该类型默认模型
    API_KEY: 'sk-xxxx'            # 你的 API Key
  apiQueSetting:                  # 外部题库接口（autoExam=2 时使用）
    url: 'http://localhost:8083'
  answerSetting:                  # 多答题源设置（顺序依次调用、失败即回退）
    tokenCheck: 1                 # 启动时对 token 有效性自检：0关闭 / 1开启
    localCacheEnable: 1           # 本地缓存默认开关(兼容项: 也可在 sources 中以 type: local 独立配置)
    localCachePath: 'questions_answers.json'  # 缓存文件(格式与题库json一致: {"题目":"答案"})
    # 调用顺序：填各答题源的【自定义名称】，逗号分隔，从高到低
    # 未列出的答题源按配置顺序排在后面；留空则全部按配置顺序
    order: '本地题库缓存, 言溪题库, AVXE题库, AI'
    # 答题源列表：支持多个题库组，每组可含多个子项(items)，组与子项均可自定义命名
    # 类型：local=本地题库缓存 / emmcy=言溪题库 / axe=AVXE题库 / ai=AI大模型
    sources:
      - name: '本地题库缓存'      # 本地缓存也是独立答题源: 可排序/可开关
        type: 'local'
        enable: 1                # 0禁用(不读也不写缓存) / 1启用
        # url: 'questions_answers.json'   # 缓存文件路径(可留空用默认)
      - name: '言溪题库'          # 自定义名称(二次命名，用于上方 order 排序)
        type: 'emmcy'
        enable: 1                # 独立启停开关：0禁用 / 1启用
        token: '你的言溪token'    # 官网个人中心获取
      - name: 'AVXE题库'
        type: 'axe'
        enable: 1
        token: '你的AVXE token'
        url: ''                   # 可留空用默认; 旧的apifox文档地址会被自动纠正
      - name: 'AI'
        type: 'ai'
        enable: 1
        token: 'sk-xxxx'         # AI 的 APIKey
        aiType: 'DEEPSEEK'       # AI 类型(同旧版 aiSetting.aiType)
        model: ''                # 可留空用默认模型

users:                            # 账号列表，支持多账号
  - accountType: 'XUEXITONG'      # 平台类型，见下方「平台类型对照表」
    url: ''                       # 部分平台需要学校专属 URL（可留空）
    remarkName: ''                # 备注名，日志中显示（可留空）
    account: '手机号/学号'
    password: '密码'
    isProxy: 0                    # 是否使用代理：0否 / 1是
    informEmails:                 # 该账号刷课状态通知邮箱（可选）
      - 'notify@email.com'
    coursesCustom:                # 该账号的课程自定义设置
      studyTime: '10-30'          # 学习时长区间（秒），随机取中间值，仅部分平台生效
      shuffleSw: 0                # 打乱课程顺序：0关闭 / 1开启
      videoModel: 1               # 刷视频模式，见下方说明
      autoExam: 0                 # 自动答题/考试模式: 0不考 / 1自动答题(多答题源) / 2同1(旧配置兼容) / 3内置AI
      examAutoSubmit: 0           # 考完自动提交试卷：0否 / 1是
      cxNode: 3                   # 【学习通】多任务点并发数
      cxChapterTestSw: 1          # 【学习通】章测开关：0关闭 / 1开启
      cxWorkSw: 1                 # 【学习通】作业开关：0关闭 / 1开启
      cxExamSw: 1                 # 【学习通】考试开关：0关闭 / 1开启
      cxExamSwAgain: 0            # 【学习通】强制重考开关：1=支持重考的考试不管分数一律重考 / 0=仅分数<60时重考
      deviceFlag: ''              # 【学习通】设备特征码（见下方说明）
      excludeCourses: []          # 排除课程（按名称过滤）
      includeCourses: []          # 只刷指定课程（按名称过滤，空=全部）
```

### 2. videoModel 刷视频模式说明

| 值 | 模式     | 说明                                                   |
|----|----------|--------------------------------------------------------|
| 0  | 不刷视频 | 跳过所有视频任务点                                     |
| 1  | 普通模式 | 按正常时长刷，最安全                                   |
| 2  | 暴力模式 | 无视前置课程限制并发同刷（部分平台会被检测到）         |
| 3  | 多任务点 | 【学习通专用】多任务点并发刷课，配合 `cxNode` 控制并发数 |

> [!TIP]
> 学习通 `videoModel: 3` 为多任务点并发模式：`cxNode` 设为几就同时刷几个任务点，并支持多课程并发；该模式已解除并发数量限制（对齐 Go 版 CxNode=-1 路径），每个节点独立 relogin 并发执行，配合多核 CPU 自适应调度可大幅提速。

### 3. autoExam 自动答题/考试模式说明

| 值 | 模式           | 说明                                       |
|----|----------------|--------------------------------------------|
| 0  | 不考           | 不进行自动答题(跳过考试/章测/作业答题)     |
| 1  | 自动答题       | 自动答题-多答题源（题库+AI+本地缓存 按 order 顺序调用），需配置 `answerSetting` |
| 2  | 自动答题       | 同 1（保留旧值兼容，同样使用多答题源）-旧配置兼容 |
| 3  | 内置AI         | 内置AI答题（学习通自带接口）               |

> [!TIP]
> 学习通考试刷完后，若支持重考：`cxExamSwAgain: 0`（默认）仅在分数低于 60 分时重考；`cxExamSwAgain: 1` 则只要还有重考机会，不管分数一律强制重考。

### 4. 多答题源说明（answerSetting）

自动答题（章测/作业/考试/讨论）统一走多答题源引擎，特性如下：

| 特性 | 说明 |
|------|------|
| 顺序调用·失败回退 | 按顺序依次调用答题源，某个源取不到答案自动转向下一个，直到拿到答案 |
| 配置极简 | 每个答题源只需填 `token`，其余参数（接口地址/请求格式/返回解析）全部内置 |
| 自定义顺序 | `order` 填写各答题源的自定义名称调整调用优先级（含"本地题库缓存"），未列出的按配置顺序排在后面 |
| 独立启停 | 每个答题源 `enable: 0/1` 可单独开启关闭（含本地题库缓存） |
| 题库组与子项 | `sources` 支持多个题库组；组内可用 `items` 配置多个子项（多个token），组名与子项名均可自定义（二次命名），子项名称同样可用于 `order` 排序 |
| 本地题库缓存 | 独立答题源（`type: local`）：可单独开关、可参与 `order` 排序；文件路径可用条目 `url` 或 `localCachePath` 指定；**外部题库/AI 答对的题目会自动写入缓存并输出日志**，下次优先命中 |
| 启动自检 | 程序启动时自动检查各答题源 token 有效性并输出结果（如剩余次数），显示本地缓存加载条数，可用 `tokenCheck: 0` 关闭 |
| 全量日志 | 每个答题源每一次被尝试调用（成功/无结果/异常/禁用/跳过）均输出日志，并明确标注每题由哪个源回答成功、是否已写入本地缓存 |

题库组 + 子项 + 本地缓存示例（同类型多个token可分别命名、按序调用）：

```yaml
  answerSetting:
    order: '本地题库缓存, 言溪小号, 言溪主号, AI'
    sources:
      - name: '本地题库缓存'
        type: 'local'
        enable: 1
      - name: '言溪题库组'
        type: 'emmcy'
        enable: 1
        items:
          - name: '言溪主号'
            token: 'token-1'
          - name: '言溪小号'
            token: 'token-2'
      - name: 'AI'
        type: 'ai'
        enable: 1
        token: 'sk-xxxx'
        aiType: 'DEEPSEEK'
```

> [!TIP]
> 兼容旧配置：若 `answerSetting` 未配置任何答题源，但旧版 `aiSetting.API_KEY` 已填写，程序会自动将旧 AI 配置作为兜底答题源使用。

### 5. AI 类型对照表（aiType）

| 值           | 服务商               | 默认模型           |
|--------------|----------------------|--------------------|
| DEEPSEEK     | DeepSeek             | deepseek-chat      |
| TONGYI       | 阿里云通义           | qwen-plus-latest   |
| CHATGLM/ZHIPU| 智谱 AI              | glm-4              |
| XINGHUO      | 讯飞星火             | generalv3.5        |
| DOUBAO       | 字节豆包             | 自定义             |
| OPENAI       | OpenAI               | 自定义             |
| SILICONFLOW  | 硅基流动             | 自定义             |
| METAAI       | 秘塔 AI              | 自定义             |
| OTHER        | 自定义接口           | 配合 aiUrl 使用    |

### 6. 平台类型对照表（accountType）

| 值         | 平台             | 备注                                 |
|------------|------------------|--------------------------------------|
| XUEXITONG  | 学习通           | 支持人脸绕过、章测/作业/考试、多任务点 |
| YINGHUA    | 英华学堂         | 支持暴力模式                         |
| HQKJ       | 海奇科技（仓辉实训） | 套壳英华版本                     |
| ENAEA      | 学习公社         | 支持倍速刷                           |
| CQIE       | 重庆工业学院     | 支持秒刷                             |
| KETANGX    | 随行课堂         | 支持秒刷完成度与学时累计             |
| ICVE       | 智慧职教         | 目前只支持 Cookie 登录               |
| QSXT       | 青书学堂         | 只支持普通模式                       |
| WELEARN    | 微学             | 移植自 Go 版                         |

### 7. 学习通 deviceFlag 设备特征码

学习通考试启用客户端签名校验时，纯 HTTP 程序无法作答，需要配置 `deviceFlag`：

1. 手机学习通 APP 内打开 `https://doc.micono.eu.org/tools/device` 获取设备特征码
2. 填入 `coursesCustom.deviceFlag`
3. 留空则每次登录自动生成（部分课程考试可能无法完成）

### 8. 学习通人脸识别说明

学习通刷课时触发人脸识别，程序会自动尝试绕过（手机端卡片人脸/PC端视频人脸两套流程）：

**自动绕过流程：**

1. **人脸图片获取**：优先读取本地 `assets/faces/{账号}.jpg`，不存在则自动拉取该账号的历史人脸图片
2. **RGB 扰动处理**：对图片做像素扰动（防平台检测）
3. **上传人脸**：获取上传 token 后上传图片，拿到 objectId
4. **更换基准 FaceId**：调用 `api/changefaceid` 将基准 FaceId 换成新上传的照片（对齐新版 APP，绕过历史基准照片限制）
5. **新接口验证**：QR码方案验证通过则继续刷课；"用户图片信息出错"自动重试 8 次
6. **老接口回退**：新接口彻底失败时自动回退老接口 `uploadInfo` 验证

**使用建议：**

- **本地人脸缓存**：可手动将本人清晰正脸照片放到 `assets/faces/{账号}.jpg`，程序优先使用本地图片（成功率更高）
- **失败处理**：若账号从未录入过人脸（提示"没有历史人脸"），需先在手机学习通 APP 完成一次人脸识别录入
- **PC端视频人脸**：视频 403 触发时走 PC 端流程（updateqrstatus/getqrstatus 轮询验证）

### 9. 启动方式

**方式一：控制台直接刷课**

```bash
python main.py
```

**方式二：Web 服务模式（可部署服务器）**

将 `setting.basicSetting.webModel` 设为 `1`，启动后 FastAPI Web 服务监听 `0.0.0.0:8080`（端口可在 `basicSetting.webPort` 修改）：

> [!TIP]
> 程序支持多开：重复启动时若端口被占用，会自动顺延到下一个空闲端口（如 8081），并在日志中提示实际监听地址。

```bash
python main.py
```

### 10. 常用场景示例

```yaml
# 示例：学习通账号，多任务点并发刷课 + AI 自动考试 + 章测/作业
users:
  - accountType: 'XUEXITONG'
    account: '13800138000'
    password: 'your_password'
    coursesCustom:
      videoModel: 3        # 多任务点并发
      cxNode: 10           # 10个任务点并发
      autoExam: 1          # 自动答题(多答题源: 题库+AI 顺序调用)
      examAutoSubmit: 1    # 自动交卷
      cxChapterTestSw: 1   # 刷章测
      cxWorkSw: 1          # 刷作业
      cxExamSw: 1          # 刷考试
      includeCourses:      # 只刷这两门课（可留空=全部）
        - '形势与政策'
        - '古代汉语'
```

### 11. 本地图片 OCR（可选，离线）

部分课程的题目/选项以**图片**形式给出，程序内置本地 OCR 自动识别为文本后再交给答题源作答：

| 引擎 | 说明 |
|------|------|
| rapidocr-onnxruntime（首选） | PaddleOCR 的 ONNX 移植，wheel 内置模型，**完全离线**，无需下载、无需联网 |
| ddddocr（降级备选） | 轻量验证码识别，同样内置模型；未安装时自动跳过 |

- 依赖已包含在 `requirements.txt`，安装即用（会自动带上 onnxruntime/numpy/opencv）
- 引擎懒加载 + 单例 + 线程安全，不影响启动速度；缺库时优雅降级，**不会中断刷课**
- Windows 加固版 exe 已内置 OCR 模型，开箱即用

## 🪟 Windows 单文件 exe（加固发布版）

打包产物：`yatori-python刷课系统V1.1.0.exe`（单文件、免安装 Python 环境）。

### 使用方法

1. 将 exe 放到任意文件夹（如 `D:\yatori`），并把 `config.yaml` 放在 **exe 同目录**
2. 双击运行；首次运行自动生成 `assets\faces`、`assets\fsces`、`assets\logs`、`assets\sound` 等目录
3. 日志输出在 `assets\logs\日期.log`；人脸图缓存放 `assets\faces\账号.jpg`（可选）
4. 本地题库缓存文件为 exe 同目录的 `questions_answers.json`（运行时自动创建/回写）

### 加固说明（防反编译 / 防逆向）

| 措施 | 说明 |
|------|------|
| 自研代码 Cython 原生编译 | `config/logic/utils/dao/entity/global_state/web` 全部编译为 `.pyd` 机器码扩展；发布产物中**不含任何自研 Python 源码与字节码**，无法通过 pyinstxtractor + 反编译器还原出源码 |
| 去除调试信息 | 不嵌入源码签名（embedsignature=False）、不生成代码注释，降低可读信息 |
| 进程池冻结适配 | 打包环境自动禁用多进程解析池并启用 freeze 保护，避免 Windows spawn 造成进程裂变 |
| 单文件封装 | 第三方依赖与内置资源封装于单文件，需先解包才能进一步分析 |

> [!NOTE]
> 如需商业级更强保护（如商业 PyArmor 的 BCC/RFT 虚拟化、Nuitka Commercial 反调试校验），需自行购买授权后在 `build_protected.py` 中接入；当前免费方案为 Cython 原生编译。

### 重新构建加固版

```bash
pip install -r requirements.txt
pip install cython setuptools pyinstaller
python build_protected.py
```

上面一条命令会自动完成：源码隔离复制 → Cython 编译为 .pyd → 裁剪源码 → 全量导入校验 → PyInstaller 打包 → 产物输出到 `dist/`。

## 🐳 Docker 部署

项目已支持容器化部署，GitHub Actions 自动构建**多处理器架构**镜像（linux/amd64 + linux/arm64）并推送到 GitHub Container Registry（GHCR）。

> 多架构镜像采用 manifest 自动分发：`docker pull` 时会根据当前机器的处理器自动拉取对应架构版本（Intel/AMD x86_64 自动获取 amd64 版，ARM64/Apple Silicon/树莓派自动获取 arm64 版）。

### 拉取镜像

```bash
docker pull ghcr.io/keaident-su/yatori-python-console:latest
```

### 运行（挂载本地 config.yaml）

```bash
docker run -d --name yatori \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/logs:/app/logs \
  ghcr.io/keaident-su/yatori-python-console:latest
```

> [!IMPORTANT]
> `config.yaml` 不会打进镜像（避免泄露账号信息），运行时必须通过 `-v` 挂载本地配置文件。

### 镜像标签

| 标签         | 说明                       |
|--------------|----------------------------|
| latest       | 最新版本（多架构，自动适配处理器） |
| V1.1.0 | 版本号（自动从 logo.txt 解析，多架构） |
| &lt;commit-sha&gt; | 提交哈希，用于回滚         |

```bash
# amd64/arm64 自动分发，无需指定架构
docker pull ghcr.io/keaident-su/yatori-python-console:v1.1.0
```

## 🎯 功能/特性

| 功能/特性                    | 状态 |
|------------------------------| ---- |
| 独立程序，不依赖浏览器        | ✅ |
| AI 自动识别跳过验证码         | ✅ |
| 人脸识别自动绕过（历史人脸/QR码方案，支持本地人脸图片缓存） | ✅ |
| 多账号同刷                    | ✅ |
| 多任务点并发（多核 CPU 自适应调度） | ✅ |
| 支持状态邮箱通知              | ✅ |
| 支持自动考试                  | ✅ |
| 答题支持 AI 大模型加持        | ✅ |
| 多答题源顺序调用（题库/AI/本地缓存，失败自动回退） | ✅ |
| 本地题库缓存自动回写（命中优先） | ✅ |
| 本地图片题 OCR 识别（离线，内置模型） | ✅ |
| Windows 加固单文件 exe（Cython 原生编译） | ✅ |
| 考试客户端签名（deviceFlag）  | ✅ |
| 灵活配置文件                  | ✅ |
| 可视化配置文件生成器          | ✅ |
| 自动继续上次记录时长刷课      | ✅ |
| 可部署服务器（FastAPI Web 服务） | ✅ |
| 部分平台支持暴力模式（无视前置课程学习限制所有视频同刷） | ✅ |

## 🎯 支持平台

| 平台             | 描述                                                        | 状态      |
|------------------|-------------------------------------------------------------|-----------|
| 英华学堂         | 支持暴力模式（会被检测到）                                  | 已完成 ✅ |
| 仓辉实训/海奇科技 | 支持暴力模式（套壳英华版本会被检测到）                      | 已完成 ✅ |
| 重庆工业学院 CQIE | 支持暴力模式（支持秒刷）                                    | 已完成 ✅ |
| 学习公社（ENAEA） | 支持暴力模式（倍速刷）                                      | 已完成 ✅ |
| 学习通           | 支持绕过人脸认证（历史人脸/QR码方案）、自动写章测/作业/考试、多课程/多任务点模式 | 已完成 ✅ |
| 随行课堂         | 支持秒刷完成度以及学时累计刷取                              | 已完成 ✅ |
| 智慧职教（ICVE）  | 默认秒刷（目前只支持 Cookie 登录方式）                      | 已完成 ✅ |
| 青书学堂         | 只支持普通模式                                              | 已完成 ✅ |
| 微学（WELEARN）   | 移植自 Go 版                                                 | 已完成 ✅ |

> [!TIP]
> 英华"限制性暴力模式"指：如果你学校英华平台的课程视频没有前置视频观看限制就可以开。前置视频观看限制 = 一个章节的视频必须先把前面章节的视频看完才能看。重庆工程学院 CQIE 可以做到真正意义上的秒刷，使用暴力模式即可。

## 📁 项目结构

```
yatori-python-console/
├── main.py                # 主入口
├── config.yaml            # 用户配置（不入库，本地创建）
├── questions_answers.json # 本地题库缓存（运行时自动创建/回写）
├── build_protected.py     # Windows 加固版流水线（Cython 编译 + PyInstaller 打包）
├── assets/                # 日志/人脸缓存等运行目录（首次运行自动生成）
├── 配置文件生成器.html      # 可视化配置生成器
├── config/                # 配置加载与模型定义
├── dao/                   # 数据库访问层（SQLite）
├── entity/                # DTO/POJO/VO 实体
├── global_state/          # 全局状态
├── logic/                 # 核心业务逻辑
│   ├── core/              # HTTP/AI客户端、多答题源引擎、题库客户端、OCR、CPU调度等基础设施
│   ├── xuexitong/         # 学习通
│   ├── yinghua/           # 英华学堂
│   ├── enaea/             # 学习公社
│   ├── cqie/              # 重庆工业学院
│   ├── ketangx/           # 随行课堂
│   ├── icve/              # 智慧职教
│   ├── qingshuxuetang/    # 青书学堂
│   ├── welearn/           # 微学
│   └── haiqikeji/         # 海奇科技（仓辉实训）
├── utils/                 # 日志、通知、邮件等工具
└── web/                   # FastAPI Web 服务
```

## ⚠️ 免责声明

> 代码已开源，程序只供技术学习使用，严禁贩卖，严禁滥用，若对相关平台造成损失立马删库（保命(doge)）。
>
> 他人或组织使用本代码进行的任何违法行为与本人无关，该代码纯技术学习交流。

## 📚 相关技术参考引用

> CxKitty 系列项目
>
> 油猴、Script Cat 相关脚本
