import React, { useEffect, useState } from 'react'
import { Plus, Trash2, Pencil, RefreshCw, LogIn, Globe } from 'lucide-react'
import { UI } from '../api'
import { useUI } from '../store'

const PLATFORMS = [
    { v: 'XUEXITONG', n: '超星学习通' },
    { v: 'YINGHUA', n: '英华学堂' },
    { v: 'ENAEA', n: '学习公社/网络党校' },
    { v: 'CQIE', n: '重庆工程学院' },
    { v: 'DZYX', n: '大众云学' },
    { v: 'ZHS', n: '智慧树' },
    { v: 'WELEARN', n: 'WeLearn随行课堂' },
    { v: 'HQKJ', n: '海旗科技' },
    { v: 'KETANGX', n: '课堂派' },
    { v: 'QSXT', n: '青书学堂' },
]

/* 需要"平台登录地址URL"的平台(2026-10-24: 大众云学纳入, 与英华学堂完全同一配置形态) */
const URL_PLATFORMS = ['YINGHUA', 'HQKJ', 'CQIE', 'WELEARN', 'DZYX']
const URL_PLACEHOLDER: Record<string, string> = {
    XUEXITONG: '',
    YINGHUA: '平台登录地址(学校专属域名, 如 https://xxx.yinghuaonline.com)',
    HQKJ: '平台登录地址(如 https://xxx.hqkj.com)',
    CQIE: '平台登录地址',
    WELEARN: '平台登录地址',
    DZYX: '平台登录地址(留空=使用全局默认基地址 xjbt.gxk.yxlearning.com)',
}

const EMPTY = {
    platformType: 'XUEXITONG', account: '', password: '', remarkName: '',
    url: '',
    videoModel: 1, cxExamPace: 1, autoExam: 1, examAutoSubmit: 2,
    studyCountCap: 1, studyCount: 400, cxExamDefaultGuard: 0,
}

export default function Accounts() {
    const { accounts, setAccounts, showToast } = useUI()
    const [loading, setLoading] = useState(false)
    const [modal, setModal] = useState<any>(null)
    const [checking, setChecking] = useState('')

    const load = async () => {
        setLoading(true)
        try { setAccounts(await UI.accounts()) }
        catch (e: any) { showToast(e.message, 'err') }
        finally { setLoading(false) }
    }
    useEffect(() => { load() }, [])

    const save = async () => {
        if (!modal.account || !modal.password) {
            return showToast('账号与密码必填', 'err')
        }
        try {
            if (modal.uid) await UI.updAccount(modal)
            else await UI.addAccount(modal)
            showToast('已保存')
            setModal(null)
            load()
        } catch (e: any) { showToast(e.message, 'err') }
    }

    const del = async (a: any) => {
        if (!confirm(`确认删除账号 ${a.account} ?`)) return
        try {
            await UI.delAccount(String(a.uid || a.account))
            showToast('已删除')
            load()
        } catch (e: any) { showToast(e.message, 'err') }
    }

    const loginCheck = async (a: any) => {
        setChecking(String(a.uid || a.account))
        try {
            const r: any = await UI.loginCheck({ uid: String(a.uid || a.account) })
            showToast(r?.msg || '检查完成')
        } catch (e: any) { showToast('检查失败: ' + e.message, 'err') }
        finally { setChecking('') }
    }

    const Field = ({ label, children, hint }: any) => (
        <div className="mb-3">
            <div className="text-xs mb-1.5" style={{ color: 'var(--subtext)' }}>{label}</div>
            {children}
            {hint && <div className="text-xs mt-1" style={{ color: 'var(--subtext)' }}>{hint}</div>}
        </div>
    )

    const needUrl = modal && URL_PLATFORMS.includes(modal.platformType)

    return (
        <div>
            <div className="flex items-center justify-between mb-5">
                <h1 className="text-xl font-bold">账号管理 <span className="text-sm font-normal" style={{ color: 'var(--subtext)' }}>({accounts.length}个)</span></h1>
                <div className="flex gap-2">
                    <button className="ybtn" onClick={load} disabled={loading}>
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> 刷新
                    </button>
                    <button className="ybtn ybtn-primary" onClick={() => setModal({ ...EMPTY })}>
                        <Plus size={14} /> 添加账号
                    </button>
                </div>
            </div>

            <div className="space-y-2">
                {accounts.map((a: any) => {
                    const uid = String(a.uid || a.account)
                    return (
                        <div key={uid} className="ycard p-4 flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <span className={a.running ? 'ytag ytag-run' : 'ytag'}>
                                    {a.running ? '运行中' : '空闲'}
                                </span>
                                <div>
                                    <div className="font-medium text-sm">
                                        {a.remarkName || a.account}
                                        <span className="ml-2 text-xs" style={{ color: 'var(--subtext)' }}>
                                            {PLATFORMS.find(p => p.v === (a.platformType || a.platform_type))?.n || a.platformType}
                                        </span>
                                    </div>
                                    <div className="text-xs mt-0.5" style={{ color: 'var(--subtext)' }}>
                                        {a.account}
                                        {a.url ? ` | ${a.url}` : ''}
                                        {a.collegeName ? ' | ' + a.collegeName : ''}
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <button className="ybtn py-1.5 px-3 text-xs"
                                    onClick={() => loginCheck(a)} disabled={checking === uid}>
                                    <LogIn size={13} /> {checking === uid ? '检查中' : '登录检查'}
                                </button>
                                <button className="ybtn py-1.5 px-3 text-xs"
                                    onClick={() => setModal({
                                        ...EMPTY, ...a,
                                        platformType: a.platformType || a.platform_type || 'XUEXITONG',
                                        url: a.url || a.URL || '',
                                    })}>
                                    <Pencil size={13} /> 编辑
                                </button>
                                <button className="ybtn ybtn-danger py-1.5 px-3 text-xs" onClick={() => del(a)}>
                                    <Trash2 size={13} /> 删除
                                </button>
                            </div>
                        </div>
                    )
                })}
                {accounts.length === 0 && !loading && (
                    <div className="ycard p-10 text-center text-sm" style={{ color: 'var(--subtext)' }}>
                        还没有账号，点击右上角「添加账号」开始
                    </div>
                )}
            </div>

            {/* 新增/编辑弹窗 */}
            {modal && (
                <div className="ymask" onClick={e => e.target === e.currentTarget && setModal(null)}>
                    <div className="ymodal">
                        <h2 className="font-bold mb-4">{modal.uid ? '编辑账号' : '添加账号'}</h2>

                        {/* ===== 平台专属配置区(2026-10-24: 所有平台同一结构同一交互) ===== */}
                        <div className="ycard-2 p-3 mb-3">
                            <div className="flex items-center gap-2 mb-2">
                                <Globe size={13} style={{ color: 'var(--primary)' }} />
                                <span className="text-xs font-medium">平台配置</span>
                                <span className="text-xs" style={{ color: 'var(--subtext)' }}>（随平台类型自动适配）</span>
                            </div>
                            <div className="grid grid-cols-2 gap-x-4">
                                <Field label="平台">
                                    <select className="yselect" value={modal.platformType}
                                        onChange={e => setModal({ ...modal, platformType: e.target.value })}>
                                        {PLATFORMS.map(p => <option key={p.v} value={p.v}>{p.n}</option>)}
                                    </select>
                                </Field>
                                <Field label="备注名">
                                    <input className="yinput" value={modal.remarkName || ''}
                                        onChange={e => setModal({ ...modal, remarkName: e.target.value })} placeholder="可选" />
                                </Field>
                                {needUrl && (
                                    <div className="col-span-2">
                                        <Field label="平台登录地址 URL"
                                            hint={modal.platformType === 'DZYX'
                                                ? '大众云学: 每个账号可填自己的平台地址(同供应商不同局点); 留空则使用「全局设置→大众云学基地址」或内置默认'
                                                : '该平台需指定学校/机构专属登录地址'}>
                                            <input className="yinput" value={modal.url || ''}
                                                onChange={e => setModal({ ...modal, url: e.target.value })}
                                                placeholder={URL_PLACEHOLDER[modal.platformType] || 'https://...'} />
                                        </Field>
                                    </div>
                                )}
                                <Field label="账号 *">
                                    <input className="yinput" value={modal.account || ''}
                                        onChange={e => setModal({ ...modal, account: e.target.value })} />
                                </Field>
                                <Field label="密码 *">
                                    <input className="yinput" type="password" value={modal.password || ''}
                                        onChange={e => setModal({ ...modal, password: e.target.value })} />
                                </Field>
                            </div>
                        </div>

                        {/* ===== 学习/考试通用配置区 ===== */}
                        <div className="ycard-2 p-3">
                            <div className="text-xs font-medium mb-2">学习与考试配置</div>
                            <div className="grid grid-cols-2 gap-x-4">
                                <Field label="视频模式 (0不刷/1串行/2并发/3多任务点)">
                                    <input className="yinput" type="number" value={modal.videoModel ?? 1}
                                        onChange={e => setModal({ ...modal, videoModel: +e.target.value })} />
                                </Field>
                                <Field label="考试节奏 (0秒答/1标准/2谨慎)">
                                    <input className="yinput" type="number" value={modal.cxExamPace ?? 1}
                                        onChange={e => setModal({ ...modal, cxExamPace: +e.target.value })} />
                                </Field>
                                <Field label="学习次数 (封顶开启时按30执行)">
                                    <input className="yinput" type="number" value={modal.studyCount ?? 400}
                                        onChange={e => setModal({ ...modal, studyCount: +e.target.value })} />
                                </Field>
                                <Field label="学习次数智能封顶">
                                    <select className="yselect" value={modal.studyCountCap ?? 1}
                                        onChange={e => setModal({ ...modal, studyCountCap: +e.target.value })}>
                                        <option value={1}>开启(封顶30,省时)</option>
                                        <option value={0}>关闭(完全按设定次数)</option>
                                    </select>
                                </Field>
                                <Field label="自动考试 (0关/1开)">
                                    <select className="yselect" value={modal.autoExam ?? 1}
                                        onChange={e => setModal({ ...modal, autoExam: +e.target.value })}>
                                        <option value={1}>开启</option>
                                        <option value={0}>关闭</option>
                                    </select>
                                </Field>
                                <Field label="考试兜底暂停保护">
                                    <select className="yselect" value={modal.cxExamDefaultGuard ?? 0}
                                        onChange={e => setModal({ ...modal, cxExamDefaultGuard: +e.target.value })}>
                                        <option value={0}>关闭(默认,推荐)</option>
                                        <option value={1}>开启</option>
                                    </select>
                                </Field>
                            </div>
                        </div>

                        <div className="flex justify-end gap-2 mt-5">
                            <button className="ybtn" onClick={() => setModal(null)}>取消</button>
                            <button className="ybtn ybtn-primary" onClick={save}>保存</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
