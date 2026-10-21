# 大众云学(yxlearning)网课平台逆向规格 V1.0

> 逆向日期: 2026-10-22 | 目标站: http://xjbt.gxk.yxlearning.com (新疆生产建设兵团公需科目平台)
> 供应商: 大众云学 (yxlearning.com 系列, 同供应商子站: sddz/sddy/xjbt 等, gxk=公需科目 / zyk=专业课)
> 参照: 油猴脚本 github.com/y869177843/yxlearning (v3.0.4, DOM自动化型, 771行)
> 测试账号: 412728199107114221 / Lb15809938922~ (姓名: 李浆, 已报班级8/通过8)
> 工具: REA工具链(全局已装) + 系统Chrome(playwright channel=chrome) + OpenCV

## 一、平台结构

| 子站 | 用途 | 备注 |
|---|---|---|
| `xjbt.gxk.yxlearning.com` | 公需科目(年度30学时课) | 本次主目标 |
| `xjbt.zyk.yxlearning.com` | 专业课/自选课程 | 同构, 导航互跳 |

- 技术栈: 服务端渲染HTML + jQuery/webpack + **百家云bplayer**(视频, ev1加密流+wasm解码)
- 接口后缀统一 `.gson`, 响应统一 `{respCode, respDesc, attribute}`
- 人脸开关: `/train/cms/face/check/class-checkface-config.gson?myClassId=` → `isCheckFace`(本课程=0无需人脸)

## 二、登录链(已攻破)

1. `GET /login` → 表单 `input[name=account]`(证件号/手机号) + `input[name=password]`
2. 点登录 → **弹滑块**(自研sliderValid组件):
   - `POST /train/common-slider/get-slider.gson`
     data: `havingfilenameKey=filename2&tokenKey=token2&location_y_Key=location_y_2&location_x_Key=location_x_2&checkSliderKey=checkSlider2`
     resp.attribute: `{shadow_width:50, shadow_height:50, slider:<滑块图b64>, bgImg:<底图b64>, width:320, height:160, location_y:78}`
   - DOM: `.slider-valid-bgimg > img.slider-valid-bg-img`(底图) + `img.slider-valid-sliderimg`(滑块, style.top≈location_y-12)
     拖拽条 `.sliderContainer .slider`; 到位后出现 `button.slider-valid-btn`("点击完成验证")
   - **缺口X求解(实测可靠)**: OpenCV `matchTemplate(bgg, fgg灰度, TM_CCORR_NORMED, mask=alpha>50)` → conf≈1.00 命中
     (注意: 必须等 img.src 为 `data:` 前缀再取图, 弹窗动画期 src 为空会取到页面URL)
   - 流程: 拟人分段拖动(18-26步+微抖) → 点 `.slider-valid-btn` → **再次点登录**
3. `POST /train/login/login.gson` (内联滑块校验; 失败 respCode=-1 "滑块校验失败" 并刷新滑块)
4. 成功 → `/index`; cookies 持久化(storage_state)可长期复用

## 三、课程/学习链

| 步骤 | 接口/页面 | 关键字段 |
|---|---|---|
| 学习列表 | `GET /train/cms/study/find-my-study-info.gson?studyStatus=&orderBy=1&pageSize=99999...` | list[]: myClassId/classId/lastCourseId/lastVideoId/studyStatus(2=完成)/studySpeed/score/continueLearn |
| 班级详情 | `GET /train/class/my-class.gson?myClassId=` | watchTimeLength/totalTimeLength/studyStatus/lastCourseId/lastVideoId/classInfo{classHour,pattern} |
| 课程页(视频) | `GET /learning/index?myClassId=` | 目录行 `.course-list .videoLi`(li.id=**videoId**), 39行/课 |
| 切课记录 | `POST /train/cms/my-video/update-last-video.gson` | classId&myClassId&myClassCourseId&myClassCourseVideoId |
| 百家云token | `GET /train/dictionary/get-baijiayun-token.gson?videoSource=<vid>` | attribute.data=token串 |
| 百家云关键帧 | `POST www.baijiayun.com/vod/video/listVideoKeyFrame` | vid |

- 视频流: `dws4jd-video-bak.baijiayun.com/.../<vid>_<hash>.ev1?t=&sign=` (**ev1加密**, 浏览器内wasm解密, 纯协议播放不可行)
- 播放器全局对象: `window.baiJiaYunPlayer` (keys: paused/currentTime/speed/quality/memoryTime/protect...)
- **起播方法(实测)**: `video.muted=true` + `baiJiaYunPlayer.setMuted(true)` + `baiJiaYunPlayer.play()`
  (不静音会被autoplay策略拦截; 起播后 bj.currentTime 实时推进)
- **进度机制**: 播放期间前端**零上报xhr**(120秒实测无progress/heartbeat); 推断=百家云服务端播放日志回调平台
  (油猴脚本同样只做播放控制, 无任何上报代码, 互证) → **自动化只需保证真实播放+页面存活**
  (已完成课程studyStatus=2不再累计watchTime, 未完成课程的累计验证留待适配开发期)
- 弹题(视频内 quiz): `.bplayer-question-wrap`(display非none即弹出) → 油猴做法: 立即隐藏+8秒后续播
- 播放按钮: `.bplayer-play-btn` / `.shade .play-btn`

## 四、考试链(待深挖)

- 入口: `/my/exam` (导航"我的考试"); 纸笔记录数 `GET /train/cms/paper/get-myRecord-count.gson`
- 当前账号"待参加考试=0", 接口细节留待有考试时补抓

## 五、适配设计建议(yatori项目集成)

1. **路线**: 浏览器自动化(playwright系统Chrome) + 接口监听, 不做纯协议(视频ev1加密+进度服务端回调)
2. **多站点泛化**: 主机名参数化(`<region>.<gxk|zyk>.yxlearning.com`), 配置里只填基地址即可适配同供应商各局点
3. **模块落点**: `logic/dazhongyunxue/` (api.py=登录/滑块/列表; part.py=学习主循环: 逐videoLi播放→弹题隐藏→播完下一讲→整课完成判定)
4. **滑块**: OpenCV ccorr_mask 模板匹配 + 失败刷新重试(≤10次), 登录态 storage_state 缓存复用
5. **拟人**: 播放倍速≤1.0(protect字段存在, 防倍速检测), 课间随机停留, 弹题按"隐藏+延时续播"

## 六、证据存档

- 抓包: `_yx_capture_login.json` / `_yx_capture_learn.json` / `_yx_capture_polyv3.json` / `_yx_capture_play4.json` / `_yx_capture_play5.json`
- 滑块图: `_yx_slider_vis_bg.png` / `_yx_slider_vis_fg.png` / `_yx_gap_zoom.png`
- 登录态: `_yx_state.json` | 参照脚本: `_yxlearning_ref/大众云学-yxlearning-自动学习-重构版-3.0.4.js`
