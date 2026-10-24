import React, { useEffect, useState } from 'react';
import { Plus, Trash2, Pencil, RefreshCw, LogIn, Globe } from 'lucide-react';
import { UI } from '../api';
import { useUI } from '../store';
import { useT } from '../i18n'
const PLATFORMS = [{
    v: 'XUEXITONG',
    n: '超星学习通'
}, {
    v: 'YINGHUA',
    n: '英华学堂'
}, {
    v: 'WEBAN',
    n: '安全微伴'
}, {
    v: 'ZHIHUISHU',
    n: '智慧树'
}, {
    v: 'ENAEA',
    n: '学习公社/网络党校'
}, {
    v: 'CQIE',
    n: '重庆工程学院'
}, {
    v: 'DZYX',
    n: '大众云学'
}, {
    v: 'WELEARN',
    n: 'WeLearn随行课堂'
}, {
    v: 'HQKJ',
    n: '海旗科技'
}, {
    v: 'KETANGX',
    n: '码上研训'
}, {
    v: 'ICVE',
    n: '智慧职教'
}, {
    v: 'QSXT',
    n: '青书学堂'
}];
const URL_PLATFORMS = ['YINGHUA', 'HQKJ', 'CQIE', 'WELEARN', 'DZYX'];
const URL_PLACEHOLDER: Record<string, string> = {
    YINGHUA: '平台登录地址(学校专属域名)',
    HQKJ: '平台登录地址',
    CQIE: '平台登录地址',
    WELEARN: '平台登录地址',
    DZYX: '平台登录地址(留空=全局默认基地址 xjbt.gxk.yxlearning.com)'
};

/* ===== CoursesCustom 全字段默认值(对齐 config.py, camelCase 与生成器/WP一致) ===== */
const CC_DEFAULT: any = {
    studyTime: '',
    cxNode: 3,
    cxChapterTestSw: 1,
    cxWorkSw: 1,
    cxExamSw: 1,
    cxInteractiveQuizSw: 1,
    cxExamSwAgain: 0,
    shuffleSw: 0,
    videoModel: 1,
    autoExam: 1,
    examAutoSubmit: 2,
    cxExamPace: 1,
    cxExamSubmitRate: 100,
    cxExamDefaultGuard: 0,
    cxExamPreCollect: 1,
    cxVerifyAnswer: 1,
    cxCollectAnswers: 1,
    otherTaskStay: 30,
    addStudySw: 0,
    addStudyCount: 0,
    addStudyVideoMinutes: 0,
    addStudyReadMinutes: 0,
    addStudyDelay: 30,
    restSw: 0,
    restStart: '23:00',
    restEnd: '06:00',
    jfSw: 0,
    // [2026-10-24] 课程过滤(与生成器/unified语义一致): 空=全部; 只刷非空=仅显示/只刷命中; 排除=剔除; 都填=交集
    includeCourses: [],
    excludeCourses: [],
    cxExamRetake: 0,
    cxRetakeRate: 80,
    cxWorkRetake: 0,
    cxExtendReadSw: 1,
    cxOtherReadSw: 1,
    cxBbsSw: 1,
    bruteSpeed: 2.4,
    deviceFlag: '',
    wbTenant: '',
    wbUserId: '',
    wbStudyMode: 1,
    wbExamMode: 1,
    wbRandomAnswer: 1,
    wbStudyTime: 20,
    wbVideoSpeed: 1.0,
    wbExamQuestionTime: 3,
    wbExamPace: 1,
    wbExamSubmitMatchRate: 90,
    zhsSpeed: 1.5,
    zhsShareSw: 1,
    zhsAiCourseSw: 1,
    zhsHikeSw: 1,
    zhsAiSmartSw: 0,
    zhsWorkSw: 0,
    zhsExamSw: 0,
    zhsExamCollectSw: 0,
    zhsExamPace: 1,
    zhsVerifyAnswer: 1,
    zhsSubmitRate: 100,
    zhsCollectOnlySw: 0,
    yhExamPace: 1,
    qsExamPace: 1,
    cqExamPace: 1
};
const EMPTY = {
    platformType: 'XUEXITONG',
    account: '',
    password: '',
    remarkName: '',
    url: '',
    informEmails: [] as string[],
    showdocSw: 0,
    showdocUrls: [] as string[],
    isProxy: 0,
    coursesCustom: {
        ...CC_DEFAULT
    }
};
const TABS = ['基础', '学习', '考试/作业', '次数/休息', '平台专属', '通知'] as const;

// [2026-10-24 修输入失焦] 子组件必须定义在模块顶层(组件函数外)。
// 之前在 Accounts() 内部定义→每次 setState 重渲染都产生新组件引用→
// React 卸载重建输入框→焦点丢失、只能输入第1个字符。
// 现改为顶层组件 + Context 传递表单值(camelCase键在 cc 内)。
const CCCtx = React.createContext<any>(null);
const Field = ({
    label,
    children,
    hint
}: any) => <div className="mb-2.5">
        <div className="text-xs mb-1" style={{
            color: 'var(--subtext)'
        }}>{label}</div>
        {children}
        {hint && <div className="text-xs mt-0.5" style={{
            color: 'var(--subtext)'
        }}>{hint}</div>}
    </div>;
const Num = ({
    k,
    label,
    min,
    max,
    hint
}: any) => {
    const {
        cc,
        updCC
    } = React.useContext(CCCtx) || {};
    return <Field label={label} hint={hint}>
        <input className="yinput" type="number" value={cc[k] ?? 0} min={min} max={max} onChange={e => updCC(k, e.target.value === '' ? 0 : +e.target.value)} />
    </Field>;
};
const Sel = ({
    k,
    label,
    opts,
    hint
}: any) => {
    const {
        cc,
        updCC
    } = React.useContext(CCCtx) || {};
    return <Field label={label} hint={hint}>
        <select className="yselect" value={cc[k] ?? opts[0][0]} onChange={e => updCC(k, isNaN(+e.target.value) ? e.target.value : +e.target.value)}>
            {opts.map(([v, n]: any) => <option key={v} value={v}>{n}</option>)}
        </select>
    </Field>;
};
const Txt = ({
    k,
    label,
    ph,
    hint
}: any) => {
    const {
        cc,
        updCC
    } = React.useContext(CCCtx) || {};
    return <Field label={label} hint={hint}>
        <input className="yinput" value={cc[k] ?? ''} placeholder={ph} onChange={e => updCC(k, e.target.value)} />
    </Field>;
};
const SW = (label: string, k: string, hint?: string) => {
    const { t } = useT()
    return <Sel k={k} label={label} hint={hint} opts={[[1, t("开启")], [0, t("关闭")]]} />;
};
export default function Accounts() {
    const { t } = useT()
    const {
        accounts,
        setAccounts,
        showToast
    } = useUI();
    const [loading, setLoading] = useState(false);
    const [modal, setModal] = useState<any>(null);
    const [tab, setTab] = useState(0);
    const [checking, setChecking] = useState('');
    // [2026-10-24] 查课选择器: 拉取账号真实课程供只刷/排除勾选
    const [picker, setPicker] = useState<any>(null);
    const openCoursePicker = async (kind: 'includeCourses' | 'excludeCourses') => {
        if (!modal?.uid) {
            return showToast(t("请先保存账号后再查课（新账号需先保存一次）"), 'err');
        }
        setPicker({
            kind,
            list: [],
            loading: true,
            checked: new Set<string>()
        });
        try {
            const d: any = await UI.courses(String(modal.uid));
            const names = (d?.courseList || []).map((c: any) => String(c.courseName || '')).filter(Boolean);
            setPicker({
                kind,
                list: names,
                loading: false,
                checked: new Set<string>()
            });
            if (!names.length) showToast(t("未获取到课程（可能登录失效或无课程）"), 'err');
        } catch (e: any) {
            setPicker(null);
            showToast(t("查课失败: ") + (e?.message || e), 'err');
        }
    };
    const applyPicker = () => {
        if (!picker) return;
        const cur: string[] = modal.coursesCustom?.[picker.kind] || [];
        const add = [...picker.checked].filter((x: string) => !cur.includes(x));
        updCC(picker.kind, [...cur, ...add]);
        setPicker(null);
        showToast(`已添加 ${add.length} 门到${picker.kind === 'includeCourses' ? t("只刷") : t("排除")}列表`);
    };
    const load = async () => {
        setLoading(true);
        try {
            setAccounts(await UI.accounts());
        } catch (e: any) {
            showToast(e.message, 'err');
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => {
        load();
    }, []);
    const cc = modal?.coursesCustom || {};
    const updCC = (k: string, v: any) => {
        setModal((m: any) => ({
            ...m,
            coursesCustom: {
                ...m.coursesCustom,
                [k]: v
            }
        }));
    };
    const save = async () => {
        if (!modal.account || !modal.password) {
            return showToast(t("账号与密码必填"), 'err');
        }
        try {
            if (modal.uid) await UI.updAccount(modal); else await UI.addAccount(modal);
            showToast(t("已保存"));
            setModal(null);
            load();
        } catch (e: any) {
            showToast(e.message, 'err');
        }
    };
    const del = async (a: any) => {
        if (!confirm(`确认删除账号 ${a.account} ?`)) return;
        try {
            await UI.delAccount(String(a.uid || a.account));
            showToast(t("已删除"));
            load();
        } catch (e: any) {
            showToast(e.message, 'err');
        }
    };
    const loginCheck = async (a: any) => {
        setChecking(String(a.uid || a.account));
        try {
            const r: any = await UI.loginCheck({
                uid: String(a.uid || a.account)
            });
            showToast(r?.msg || t("检查完成"));
        } catch (e: any) {
            showToast(t("检查失败: ") + e.message, 'err');
        } finally {
            setChecking('');
        }
    };

    // [2026-10-24] 子组件已提升到模块顶层，此处不再定义(修输入失焦)。
    const pt = (modal?.platformType || modal?.accountType || '') as string;
    const needUrl = modal && URL_PLATFORMS.includes(pt);
    return <CCCtx.Provider value={{
        cc,
        updCC
    }}>
        <div>
            <div className="flex items-center justify-between mb-5">
                <h1 className="text-xl font-bold">{t("账号管理")}<span className="text-sm font-normal" style={{
                    color: 'var(--subtext)'
                }}>({accounts.length}{t("个)")}</span></h1>
                <div className="flex gap-2">
                    <button className="ybtn" onClick={load} disabled={loading}>
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{t("刷新")}</button>
                    <button className="ybtn ybtn-primary" onClick={() => {
                        setModal({
                            ...EMPTY,
                            coursesCustom: {
                                ...CC_DEFAULT
                            }
                        });
                        setTab(0);
                    }}>
                        <Plus size={14} />{t("添加账号")}</button>
                </div>
            </div>

            <div className="space-y-2">
                {accounts.map((a: any) => {
                    const uid = String(a.uid || a.account);
                    return <div key={uid} className="ycard p-4 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <span className={a.running ? 'ytag ytag-run' : 'ytag'}>
                                {a.running ? t("运行中") : t("空闲")}
                            </span>
                            <div>
                                <div className="font-medium text-sm">
                                    {a.remarkName || a.account}
                                    <span className="ml-2 text-xs" style={{
                                        color: 'var(--subtext)'
                                    }}>
                                        {t(PLATFORMS.find(p => p.v === (a.platformType || a.accountType))?.n || a.platformType || a.accountType || '')}
                                    </span>
                                </div>
                                <div className="text-xs mt-0.5" style={{
                                    color: 'var(--subtext)'
                                }}>
                                    {a.account}{a.url ? ` | ${a.url}` : ''}
                                    {/* [V3.0.9] 身份三要素展示: 学校 · 姓名 · 学号(有则显示) */}
                                    {a.school ? ` | ${a.school}` : ''}
                                    {a.realName ? ` · ${a.realName}` : ''}
                                    {a.stuNo ? ` · 学号${a.stuNo}` : ''}
                                    {!a.school && !a.realName && a.collegeName ? ' | ' + a.collegeName : ''}
                                </div>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <button className="ybtn py-1.5 px-3 text-xs" onClick={() => loginCheck(a)} disabled={checking === uid}>
                                <LogIn size={13} /> {checking === uid ? t("检查中") : t("登录检查")}
                            </button>
                            <button className="ybtn py-1.5 px-3 text-xs" onClick={() => {
                                setModal({
                                    ...EMPTY,
                                    ...a,
                                    platformType: a.platformType || a.accountType || 'XUEXITONG',
                                    url: a.url || a.URL || '',
                                    coursesCustom: {
                                        ...CC_DEFAULT,
                                        ...(a.coursesCustom || {})
                                    },
                                    informEmails: a.informEmails || [],
                                    showdocUrls: a.showdocUrls || []
                                });
                                setTab(0);
                            }}>
                                <Pencil size={13} />{t("编辑")}</button>
                            <button className="ybtn ybtn-danger py-1.5 px-3 text-xs" onClick={() => del(a)}>
                                <Trash2 size={13} />{t("删除")}</button>
                        </div>
                    </div>;
                })}
                {accounts.length === 0 && !loading && <div className="ycard p-10 text-center text-sm" style={{
                    color: 'var(--subtext)'
                }}>{t("还没有账号，点击右上角「添加账号」开始")}</div>}
            </div>

            {modal && <div className="ymask" onClick={e => e.target === e.currentTarget && setModal(null)}>
                <div className="ymodal" style={{
                    width: 'min(860px, 94vw)',
                    maxHeight: '90vh',
                    display: 'flex',
                    flexDirection: 'column'
                }}>
                    <div className="flex items-center justify-between mb-3" style={{
                        flexShrink: 0
                    }}>
                        <h2 className="font-bold">{modal.uid ? t("编辑账号") : t("添加账号")}
                            <span className="ml-2 text-xs font-normal" style={{
                                color: 'var(--subtext)'
                            }}>{t("（全部配置项与配置文件生成器对齐）")}</span>
                        </h2>
                        <div className="flex gap-1.5">
                            {TABS.map((tb, i) => <button key={tb} className="ybtn py-1 px-3 text-xs" style={{
                                background: tab === i ? 'var(--primary)' : 'var(--panel-2)',
                                color: tab === i ? '#fff' : 'var(--text)',
                                borderColor: tab === i ? 'var(--primary)' : 'var(--border)'
                            }} onClick={() => setTab(i)}>{t(tb)}</button>)}
                        </div>
                    </div>

                    {/* [2026-10-24] Tab内容区可滚动 + 底部保存按钮吸底:
                             防止长表单在小窗口下把"保存"挤出可视区导致"点不到/没动静" */}
                    <div style={{
                        flex: 1,
                        overflowY: 'auto',
                        minHeight: 0,
                        paddingRight: 4
                    }} className="yform-scroll">
                        {tab === 0 && <div className="grid grid-cols-2 gap-x-4">
                            <Field label={t("平台")}>
                                <select className="yselect" value={modal.platformType} onChange={e => setModal({
                                    ...modal,
                                    platformType: e.target.value
                                })}>
                                    {PLATFORMS.map(p => <option key={p.v} value={p.v}>{t(p.n)}</option>)}
                                </select>
                            </Field>
                            <Field label={t("备注名")}>
                                <input className="yinput" value={modal.remarkName || ''} onChange={e => setModal({
                                    ...modal,
                                    remarkName: e.target.value
                                })} placeholder={t("可选")} />
                            </Field>
                            {needUrl && <div className="col-span-2">
                                <Field label={t("平台登录地址 URL")} hint={pt === 'DZYX' ? t("大众云学: 每账号可填自己的平台地址; 留空=全局基地址或内置默认") : t("该平台需指定专属登录地址")}>
                                    <input className="yinput" value={modal.url || ''} onChange={e => setModal({
                                        ...modal,
                                        url: e.target.value
                                    })} placeholder={URL_PLACEHOLDER[pt] || 'https://...'} />
                                </Field>
                            </div>}
                            <Field label={t("账号 *")}>
                                <input className="yinput" value={modal.account || ''} onChange={e => setModal({
                                    ...modal,
                                    account: e.target.value
                                })} />
                            </Field>
                            <Field label={t("密码 *")}>
                                <input className="yinput" type="password" value={modal.password || ''} onChange={e => setModal({
                                    ...modal,
                                    password: e.target.value
                                })} />
                            </Field>
                        </div>}

                        {/* ===== Tab1 学习 ===== */}
                        {tab === 1 && <div>
                            {/* [2026-10-24] 课程过滤(学习Tab顶部): 只刷/排除, 每行一门; 支持查课选择 */}
                            <div className="grid grid-cols-2 gap-x-4" style={{
                                paddingBottom: 8,
                                marginBottom: 8,
                                borderBottom: '1px dashed var(--border)'
                            }}>
                                <Field label={t("只刷课程（每行一门；留空=不过滤；与排除同时填写时取交集）")} hint={t("课程名包含关键词即命中（模糊匹配）")}>
                                    <textarea className="yinput" rows={3} value={(cc.includeCourses || []).join('\n')} onChange={e => updCC('includeCourses', e.target.value.split('\n').map((x: string) => x.trim()).filter(Boolean))} placeholder={t("创新创业\n垃圾分类")} />
                                    <button className="ybtn py-1 px-3 text-xs mt-1" type="button" onClick={() => openCoursePicker('includeCourses')}>{t("查课并加入只刷")}</button>
                                </Field>
                                <Field label={t("排除课程（每行一门；留空=不排除）")} hint={t("命中排除列表的课程不刷、不在进度页显示")}>
                                    <textarea className="yinput" rows={3} value={(cc.excludeCourses || []).join('\n')} onChange={e => updCC('excludeCourses', e.target.value.split('\n').map((x: string) => x.trim()).filter(Boolean))} placeholder={t("大学英语\n高等数学")} />
                                    <button className="ybtn py-1 px-3 text-xs mt-1" type="button" onClick={() => openCoursePicker('excludeCourses')}>{t("查课并加入排除")}</button>
                                </Field>
                            </div>
                            <div className="grid grid-cols-3 gap-x-4">
                                <Sel k="videoModel" label={t("观看视频模式")} opts={[[0, t("0 不刷")], [1, t("1 串行")], [2, t("2 并发课程")], [3, t("3 多任务点")]]} />
                                <Num k="cxNode" label={t("多任务点数量(cxNode)")} hint={t("videoModel=3时生效")} />
                                <Num k="otherTaskStay" label={t("其它任务点停留(秒)")} />
                                {SW(t("章测开关(cxChapterTestSw)"), 'cxChapterTestSw')}
                                {SW(t("作业开关(cxWorkSw)"), 'cxWorkSw')}
                                {SW(t("互动测验(视频弹题)"), 'cxInteractiveQuizSw')}
                                {SW(t("拓展阅读"), 'cxExtendReadSw')}
                                {SW(t("其他阅读(图文素材)"), 'cxOtherReadSw')}
                                {SW(t("讨论区(cxBbsSw)"), 'cxBbsSw')}
                                {SW(t("打乱顺序(shuffleSw)"), 'shuffleSw')}
                                <Txt k="studyTime" label={t("学习时段(studyTime)")} ph={t("如 08:00-22:00, 可空")} />
                            </div>
                        </div>}

                        {/* ===== Tab2 考试/作业 ===== */}
                        {tab === 2 && <div className="grid grid-cols-3 gap-x-4">
                            {SW(t("考试开关(cxExamSw)"), 'cxExamSw')}
                            {SW(t("自动考试(autoExam)"), 'autoExam')}
                            <Sel k="examAutoSubmit" label={t("自动交卷")} opts={[[0, t("关闭")], [1, t("仅1次")], [2, t("自动全部")]]} />
                            <Sel k="cxExamPace" label={t("考试拟人节奏")} opts={[[0, t("0 秒答(高风险)")], [1, t("1 标准")], [2, t("2 谨慎")]]} />
                            <Num k="cxExamSubmitRate" label={t("正确率提交(%)")} min={0} max={100} hint={t("100=满分作答; <100随机降级防完美卷")} />
                            {SW(t("兜底暂停交卷保护(cxExamDefaultGuard)"), 'cxExamDefaultGuard', t("默认关；到点强制收卷场景下靠智能兜底"))}
                            {SW(t("考前采集(cxExamPreCollect)"), 'cxExamPreCollect', t("已完成可查看的考试自动采集入库"))}
                            {SW(t("强制重考(cxExamSwAgain)"), 'cxExamSwAgain', t("可重考的考试不管分数都重考"))}
                            <Num k="cxExamRetake" label={t("自动重考次数(cxExamRetake)")} hint={t("0=不重考")} />
                            {SW(t("答题后核对答案(cxVerifyAnswer)"), 'cxVerifyAnswer')}
                            {SW(t("题目采集归档(cxCollectAnswers)"), 'cxCollectAnswers')}
                            <Num k="cxRetakeRate" label={t("重考阈值率(cxRetakeRate)")} hint={t("作业/考试重做阈值")} />
                            {SW(t("作业强制重做(cxWorkRetake)"), 'cxWorkRetake')}
                        </div>}

                        {/* ===== Tab3 次数/休息 ===== */}
                        {tab === 3 && <div className="grid grid-cols-3 gap-x-4">
                            {SW(t("增加学习次数/时长(addStudySw)"), 'addStudySw')}
                            <Num k="addStudyCount" label={t("学习次数")} hint={t("封顶开启时按30执行")} />
                            <Num k="addStudyVideoMinutes" label={t("视频时长(分钟)")} />
                            <Num k="addStudyReadMinutes" label={t("阅读时长(分钟)")} />
                            <Num k="addStudyDelay" label={t("上报间隔(秒)")} hint={t("建议≥30")} />
                            {SW(t("夜间休息(restSw)"), 'restSw')}
                            <Txt k="restStart" label={t("休息开始(HH:MM)")} ph="23:00" />
                            <Txt k="restEnd" label={t("休息结束(HH:MM)")} ph="06:00" />
                            {SW(t("积分课自动检测(jfSw)"), 'jfSw')}
                        </div>}

                        {/* ===== Tab4 平台专属 ===== */}
                        {tab === 4 && <div>
                            {pt === 'XUEXITONG' && <div className="grid grid-cols-2 gap-x-4">
                                <Txt k="deviceFlag" label={t("设备特征码(deviceFlag)")} ph={t("学习通APP内获取, 用于考试客户端签名, 可留空")} />
                            </div>}
                            {pt === 'WEBAN' && <div className="grid grid-cols-3 gap-x-4">
                                <Txt k="wbTenant" label={t("学校全称(wbTenant) *")} ph={t("与登录页学校名称完全一致")} />
                                <Txt k="wbUserId" label={t("Token用户ID(wbUserId)")} ph={t("留空则用密码登录")} />
                                <Sel k="wbStudyMode" label={t("学习模式")} opts={[[0, t("不学习")], [1, t("正常学习")], [2, t("强制重新学习")]]} />
                                <Sel k="wbExamMode" label={t("考试模式")} opts={[[0, t("不考试")], [1, t("正常")], [2, t("追求满分")], [3, t("强制重考")]]} />
                                {SW(t("题库外随机作答"), 'wbRandomAnswer')}
                                <Num k="wbStudyTime" label={t("每课学习时长(秒)")} />
                                <Num k="wbVideoSpeed" label={t("视频倍速")} hint={t("1.0原速/8/30/≥120秒刷")} />
                                <Num k="wbExamQuestionTime" label={t("每题等待(秒)")} />
                                <Sel k="wbExamPace" label={t("考试拟人节奏")} opts={[[0, t("固定0.5s")], [1, t("标准")], [2, t("谨慎")]]} />
                                <Num k="wbExamSubmitMatchRate" label={t("最低匹配率交卷(%)")} />
                            </div>}
                            {pt === 'ZHIHUISHU' && <div className="grid grid-cols-3 gap-x-4">
                                <Num k="zhsSpeed" label={t("刷课速度倍率")} hint={t("0.3~120, 常用1.5/8/30")} />
                                {SW(t("共享课(zhsShareSw)"), 'zhsShareSw')}
                                {SW(t("AI智课(zhsAiCourseSw)"), 'zhsAiCourseSw')}
                                {SW(t("徒步课(zhsHikeSw)"), 'zhsHikeSw')}
                                {SW(t("AI智慧学习(zhsAiSmartSw)"), 'zhsAiSmartSw')}
                                {SW(t("作业(zhsWorkSw)"), 'zhsWorkSw')}
                                {SW(t("考试(zhsExamSw)"), 'zhsExamSw')}
                                {SW(t("考试采集(zhsExamCollectSw)"), 'zhsExamCollectSw')}
                                <Sel k="zhsExamPace" label={t("考试节奏")} opts={[[0, t("秒答")], [1, t("标准")], [2, t("谨慎")]]} />
                                {SW(t("答案核对(zhsVerifyAnswer)"), 'zhsVerifyAnswer')}
                                <Num k="zhsSubmitRate" label={t("提交正确率(%)")} />
                                {SW(t("只采集(zhsCollectOnlySw)"), 'zhsCollectOnlySw')}
                            </div>}
                            {['YINGHUA', 'ENAEA', 'CQIE', 'KETANGX', 'HQKJ', 'ICVE', 'QSXT', 'WELEARN', 'DZYX'].includes(pt) && <div className="grid grid-cols-3 gap-x-4">
                                <Num k="bruteSpeed" label={t("暴力模式倍速(bruteSpeed)")} hint={t("部分平台生效, 最低2.4")} />
                                <Sel k="yhExamPace" label={t("英华考试节奏")} opts={[[0, t("秒答")], [1, t("标准")], [2, t("谨慎")]]} />
                                <Sel k="qsExamPace" label={t("青书考试节奏")} opts={[[0, t("秒答")], [1, t("标准")], [2, t("谨慎")]]} />
                                <Sel k="cqExamPace" label={t("CQIE考试节奏")} opts={[[0, t("秒答")], [1, t("标准")], [2, t("谨慎")]]} />
                            </div>}
                            {!['XUEXITONG', 'WEBAN', 'ZHIHUISHU', 'YINGHUA', 'ENAEA', 'CQIE', 'KETANGX', 'HQKJ', 'ICVE', 'QSXT', 'WELEARN', 'DZYX'].includes(pt) && <div className="text-xs py-4 text-center" style={{
                                color: 'var(--subtext)'
                            }}>{t("该平台暂无专属配置项")}</div>}
                        </div>}

                        {/* ===== Tab5 通知 ===== */}
                        {tab === 5 && <div>
                            <Field label={t("通知邮箱(每行一个)")}>
                                <textarea className="yinput" rows={3} value={(modal.informEmails || []).join('\n')} onChange={e => setModal({
                                    ...modal,
                                    informEmails: e.target.value.split('\n').filter(x => x.trim())
                                })} placeholder="a@qq.com&#10;b@qq.com" />
                            </Field>
                            <div className="grid grid-cols-2 gap-x-4">
                                <Field label={t("ShowDoc推送")}>
                                    <select className="yselect" value={modal.showdocSw ?? 0} onChange={e => setModal({
                                        ...modal,
                                        showdocSw: +e.target.value
                                    })}>
                                        <option value={0}>{t("关闭")}</option><option value={1}>{t("开启")}</option>
                                    </select>
                                </Field>
                                <Field label={t("使用代理(isProxy)")}>
                                    <select className="yselect" value={modal.isProxy ?? 0} onChange={e => setModal({
                                        ...modal,
                                        isProxy: +e.target.value
                                    })}>
                                        <option value={0}>{t("不使用")}</option><option value={1}>{t("使用")}</option>
                                    </select>
                                </Field>
                            </div>
                            <Field label={t("ShowDoc地址(每行一个)")}>
                                <textarea className="yinput" rows={2} value={(modal.showdocUrls || []).join('\n')} onChange={e => setModal({
                                    ...modal,
                                    showdocUrls: e.target.value.split('\n').filter(x => x.trim())
                                })} placeholder="https://push.showdoc.com.cn/server/api/push/xxx" />
                            </Field>
                        </div>}
                    </div>

                    {picker && <div className="ymask" style={{
                        zIndex: 60
                    }} onClick={e => e.target === e.currentTarget && setPicker(null)}>
                        <div className="ymodal" style={{
                            width: 'min(640px, 92vw)',
                            maxHeight: '80vh',
                            display: 'flex',
                            flexDirection: 'column'
                        }}>
                            <div className="font-bold mb-2">{t("查课选择（")}{picker.kind === 'includeCourses' ? t("加入只刷") : t("加入排除")}）
                            </div>
                            <div style={{
                                flex: 1,
                                overflowY: 'auto',
                                minHeight: 120
                            }}>
                                {picker.loading && <div className="text-sm p-4" style={{
                                    color: 'var(--subtext)'
                                }}>{t("正在拉取课程（首次约15～60秒）…")}</div>}
                                {!picker.loading && picker.list.map((n: string) => <label key={n} className="flex items-center gap-2 text-sm py-1.5" style={{
                                    borderBottom: '1px solid var(--border)'
                                }}>
                                    <input type="checkbox" checked={picker.checked.has(n)} onChange={e => {
                                        const s = new Set<string>(picker.checked);
                                        if (e.target.checked) s.add(n); else s.delete(n);
                                        setPicker({
                                            ...picker,
                                            checked: s
                                        });
                                    }} />
                                    <span>{n}</span>
                                </label>)}
                            </div>
                            <div className="flex justify-end gap-2 mt-3" style={{
                                flexShrink: 0
                            }}>
                                <button className="ybtn" onClick={() => setPicker(null)}>{t("取消")}</button>
                                <button className="ybtn ybtn-primary" onClick={applyPicker} disabled={picker.loading || picker.checked.size === 0}>{t("加入列表（")}{picker.checked.size}）
                                </button>
                            </div>
                        </div>
                    </div>}

                    <div className="flex justify-between items-center mt-3" style={{
                        flexShrink: 0,
                        borderTop: '1px solid var(--border)',
                        paddingTop: 10
                    }}>
                        <span className="text-xs" style={{
                            color: 'var(--subtext)'
                        }}>{t("配置项与「配置文件生成器」一致（课程自定义 coursesCustom 全量）")}</span>
                        <div className="flex gap-2">
                            <button className="ybtn" onClick={() => setModal(null)}>{t("取消")}</button>
                            <button className="ybtn ybtn-primary" onClick={save}>{t("保存")}</button>
                        </div>
                    </div>
                </div>
            </div>}
        </div>
    </CCCtx.Provider>;
}