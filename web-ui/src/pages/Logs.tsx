import React, { useEffect, useRef, useState } from 'react'
import { RefreshCw, ScrollText } from 'lucide-react'
import { UI } from '../api'
import { useUI } from '../store'

export default function Logs() {
    const { accounts, showToast } = useUI()
    const [acct, setAcct] = useState('')
    const [date, setDate] = useState('')
    const [text, setText] = useState('')
    const [auto, setAuto] = useState(true)
    const [loading, setLoading] = useState(false)
    const boxRef = useRef<HTMLDivElement>(null)

    const load = async (silent = false) => {
        if (!silent) setLoading(true)
        try {
            const d: any = await UI.logTail(acct, date, 400)
            const t = d?.lines ? d.lines.join('\n') : (d?.text || d?.data || '')
            setText(typeof t === 'string' ? t : JSON.stringify(t))
            // 自动滚底
            requestAnimationFrame(() => {
                const el = boxRef.current
                if (el) el.scrollTop = el.scrollHeight
            })
        } catch (e: any) {
            if (!silent) showToast(e.message, 'err')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { load() }, [acct, date])
    useEffect(() => {
        if (!auto) return
        const t = setInterval(() => load(true), 5000)
        return () => clearInterval(t)
    }, [auto, acct, date])

    return (
        <div className="flex flex-col h-[calc(100vh-120px)]">
            <div className="flex items-center justify-between mb-4">
                <h1 className="text-xl font-bold">日志中心</h1>
                <div className="flex items-center gap-2">
                    <select className="yselect w-48" value={acct} onChange={e => setAcct(e.target.value)}>
                        <option value="">全部账号</option>
                        {accounts.map((a: any) => (
                            <option key={String(a.uid || a.account)} value={String(a.uid || a.account)}>
                                {a.remarkName || a.account}
                            </option>
                        ))}
                    </select>
                    <input className="yinput w-36" value={date} placeholder="日期 如2026-10-23"
                        onChange={e => setDate(e.target.value)} />
                    <label className="flex items-center gap-1 text-xs cursor-pointer" style={{ color: 'var(--subtext)' }}>
                        <input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> 自动刷新(5s)
                    </label>
                    <button className="ybtn" onClick={() => load()} disabled={loading}>
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            <div ref={boxRef}
                className="ycard flex-1 overflow-auto p-4 font-mono text-xs whitespace-pre-wrap leading-5"
                style={{ color: 'var(--text)' }}>
                {text || <span style={{ color: 'var(--subtext)' }}>
                    <ScrollText size={14} className="inline mr-2" />暂无日志（选择账号查看其专属日志，或刷课启动后自动产生）
                </span>}
            </div>
        </div>
    )
}
