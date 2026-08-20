# Yatori-Python-Console

> 本项目是借助 AI 基于 [yatori-go-console](https://github.com/yatori-dev/yatori-go-console) 重构的 **Python 版本** 多平台网课自动刷课工具。
>
> 独立程序、不依赖浏览器，支持多账号并行、多任务点并发刷课。

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
    webModel: 0                   # Web模式：0关闭 / 1启动 FastAPI Web 服务(端口8080)
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
      autoExam: 0                 # 自动考试：0不考试 / 1AI考试 / 2外部题库对接
      examAutoSubmit: 0           # 考完自动提交试卷：0否 / 1是
      cxNode: 3                   # 【学习通】多任务点并发数
      cxChapterTestSw: 1          # 【学习通】章测开关：0关闭 / 1开启
      cxWorkSw: 1                 # 【学习通】作业开关：0关闭 / 1开启
      cxExamSw: 1                 # 【学习通】考试开关：0关闭 / 1开启
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

### 3. autoExam 自动考试说明

| 值 | 模式           | 说明                                       |
|----|----------------|--------------------------------------------|
| 0  | 不考试         | 跳过考试任务                               |
| 1  | AI 考试        | 调用 AI 大模型自动答题，需配置 `aiSetting` |
| 2  | 外部题库对接   | 对接外部题库接口，需配置 `apiQueSetting`   |

### 4. AI 类型对照表（aiType）

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

### 5. 平台类型对照表（accountType）

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

### 6. 学习通 deviceFlag 设备特征码

学习通考试启用客户端签名校验时，纯 HTTP 程序无法作答，需要配置 `deviceFlag`：

1. 手机学习通 APP 内打开 `https://doc.micono.eu.org/tools/device` 获取设备特征码
2. 填入 `coursesCustom.deviceFlag`
3. 留空则每次登录自动生成（部分课程考试可能无法完成）

### 7. 启动方式

**方式一：控制台直接刷课**

```bash
python main.py
```

**方式二：Web 服务模式（可部署服务器）**

将 `setting.basicSetting.webModel` 设为 `1`，启动后 FastAPI Web 服务监听 `0.0.0.0:8080`：

```bash
python main.py
```

### 8. 常用场景示例

```yaml
# 示例：学习通账号，多任务点并发刷课 + AI 自动考试 + 章测/作业
users:
  - accountType: 'XUEXITONG'
    account: '13800138000'
    password: 'your_password'
    coursesCustom:
      videoModel: 3        # 多任务点并发
      cxNode: 10           # 10个任务点并发
      autoExam: 1          # AI 自动考试
      examAutoSubmit: 1    # 自动交卷
      cxChapterTestSw: 1   # 刷章测
      cxWorkSw: 1          # 刷作业
      cxExamSw: 1          # 刷考试
      includeCourses:      # 只刷这两门课（可留空=全部）
        - '形势与政策'
        - '古代汉语'
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
├── 配置文件生成器.html      # 可视化配置生成器
├── config/                # 配置加载与模型定义
├── dao/                   # 数据库访问层（SQLite）
├── entity/                # DTO/POJO/VO 实体
├── global_state/          # 全局状态
├── logic/                 # 核心业务逻辑
│   ├── core/              # HTTP客户端、AI客户端、CPU进程池等基础设施
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
