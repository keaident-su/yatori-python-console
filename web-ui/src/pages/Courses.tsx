import React, { useEffect, useState } from 'react'
import { RefreshCw, BookOpen, ChevronDown, ChevronUp } from 'lucide-react'
import { UI } from '../api'
import { useUI } from '../store'

export default function Courses() {
    const { accounts, showToast } = useUI()
    const [uid, setUid] = useState('')
    const [list, setList] = useState<any[]>([])
    const [loading, setLoading] = useState(false)
    const [openId, setOpenId] = useState('')

    useEffect(() => {
        if (!uid && accounts.length) setUid(String(accounts[0].uid || accounts[0].account))
    }, [accounts])

    const load = async (force = false) => {
        if (!uid) return
        setLoading(true)
        try {
            const d: any = await UI.courses(uid, force)
            const courses = Array.isArray(d) ? d : (d?.courses || d?.data?.courses || d?.list || [])
            setList(Array.isArray(courses) ? courses : [])
        } catch (e: any) { showToast(e.message, 'err') }
        finally { setLoading(false) }
    }
    useEffect(() => { if (uid) load() }, [uid])

    const pct = (c: any) => {
        const f = +(c.jobFinishCount ?? c.finishCount ?? 0)
        const t = +(c.jobCount ?? c.taskCount ?? 0)
        return t > 0 ? Math.round(f * 100 / t) : 0
    }

    return (
        <div>
            <div className="flex items-center justify-between mb-5">
                <h1 className="text-xl font-bold">课程进度</h1>
                <div className="flex gap-2 items-center">
                    <select className="yselect w-56" value={uid} onChange={e => setUid(e.target.value)}>
                        {accounts.map((a: any) => (
                            <option key={String(a.uid || a.account)} value={String(a.uid || a.account)}>
                                {a.remarkName || a.account}
                            </option>
                        ))}
                    </select>
                    <button className="ybtn" onClick={() => load(true)} disabled={loading || !uid}>
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> 刷新(强刷)
                    </button>
                </div>
            </div>

            {loading && <div className="ycard p-10 text-center text-sm" style={{ color: 'var(--subtext)' }}>加载课程中(首次可能30秒)...</div>}

            <div className="space-y-2">
                {!loading && list.map((c: any) => {
                    const id = String(c.courseId || c.course_id || c.key)
                    const open = openId === id
                    const p = pct(c)
                    return (
                        <div key={id} className="ycard overflow-hidden">
                            <div className="p-4 flex items-center justify-between cursor-pointer"
                                onClick={() => setOpenId(open ? '' : id)}>
                                <div className="flex items-center gap-3 flex-1 min-w-0">
                                    <BookOpen size={16} style={{ color: 'var(--primary)' }} className="shrink-0" />
                                    <div className="min-w-0">
                                        <div className="font-medium text-sm truncate">{c.courseName || c.course_name}</div>
                                        <div className="text-xs mt-0.5" style={{ color: 'var(--subtext)' }}>
                                            任务点 {c.jobFinishCount ?? 0}/{c.jobCount ?? 0}
                                            {c.teacherName ? ' | ' + c.teacherName : ''}
                                        </div>
                                    </div>
                                </div>
                                <div className="flex items-center gap-3 w-56 shrink-0">
                                    <div className="yprogress flex-1"><i style={{ width: p + '%' }} /></div>
                                    <span className="text-xs w-10 text-right" style={{ color: p >= 100 ? 'var(--ok)' : 'var(--subtext)' }}>{p}%</span>
                                    {open ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                                </div>
                            </div>
                            {open && (
                                <div className="px-4 pb-4 text-xs space-y-1.5" style={{ color: 'var(--subtext)' }}>
                                    {(c.examItems || []).length > 0 && (
                                        <div className="ycard-2 p-2.5">
                                            <span className="font-medium" style={{ color: 'var(--warn)' }}>考试: </span>
                                            {(c.examItems || []).map((e: any, i: number) => (
                                                <span key={i} className="mr-3">
                                                    {e.name}［{e.status}］
                                                </span>
                                            ))}
                                            {c.examGateHint ? <div className="mt-1" style={{ color: 'var(--warn)' }}>{c.examGateHint}</div> : null}
                                        </div>
                                    )}
                                    <div>状态: {c.jobFinishCount >= c.jobCount && c.jobCount > 0 ? '任务点已完成' : '学习中'}
                                        {c.studyCount != null ? ` | 学习次数: ${c.studyCount}` : ''}
                                        {c.ccid ? ` | 班级ID: ${c.ccid}` : ''}
                                    </div>
                                </div>
                            )}
                        </div>
                    )
                })}
                {!loading && uid && list.length === 0 && (
                    <div className="ycard p-10 text-center text-sm" style={{ color: 'var(--subtext)' }}>
                        暂无课程数据（请确认账号已登录/进行过登录检查）
                    </div>
                )}
            </div>
        </div>
    )
}
