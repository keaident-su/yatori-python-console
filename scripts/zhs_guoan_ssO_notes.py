# 智慧树国安教育(polymas系) SSO+待办API - 2026-10-15逆向成果
# 通路: browser_login刷新 -> SSO链(login.zhihuishu.com?redirect=cloudapi.polymas.com/oauth/login/ssoLogin?redirect=hike-teaching-center.polymas.com) -> 根路径渲染 -> 左菜单[作业任务]
# 关键API: GET cloudapi.polymas.com/student-course/stu/todo/findNoFinishTaskTotal?keyword=&type=&pageNum=1&pageSize=20
# 国安课程: courseId=MRaAgyVMN0fG3r5zyxpZ classId=Lt92TWlyVs; 作业: activityTaskId=9VDE93p2bvIGKq3ZBDjG (图文报告1500字,截止2026-11-30)
# 注意: 深链(study/student/index)会白屏, 必须从根路径 https://hike-teaching-center.polymas.com/ 进SPA
