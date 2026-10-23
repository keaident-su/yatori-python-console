import React, { useEffect, useState } from 'react'
import { Plus, Trash2, Save, Database, RefreshCw } from 'lucide-react'
import { UI } from '../api'
import { useUI } from '../store'

const AI_TYPES = ['DEEPSEEK', 'TONGYI', 'CHATGLM', 'XINGHUO', 'DOUBAO', 'OPENAI', 'SILICON', 'METAAI', 'OTHER']
const TYPES = ['', 'ee', 'enncy', 'AI', 'APIQUE', 'emmcy']

export default function QuestionBank() {
    const { showToast } = useUI()
    const [sources, setSources] = useState<any[]>([])
    const [order, setOrder] = useState('')
    const [loading, setLoading] = useState(false)

    const load = async () => {
        setLoading(true)
        try {
            const d: any = await UI.answerSources()
            setSources(d.sources || [])
            setOrder(d.order || '')
        } catch (e: any) { showToast(e.message, 'err') }
        finally { setLoading(false) }
    }
    useEffect(() => { load() }, [])

    const save = async () => {
        try {
            await UI.saveAnswerSources({ sources, order })
            showToast('答题源已保存并生效')
        } catch (e: any) { showToast(e.message, 'err') }
    }

    const add = (type: string) => {
        setSources([...sources, {
            name: '', type, enable: 1, token: '', aiType: 'DEEPSEEK', model: '', url: '',
        }])
    }

    const upd = (i: number, k: string, v: any) => {
        const arr = [...sources]
        arr[i] = { ...arr[i], [k]: v }
        setSources(arr)
    }

    return (
        <div>
            <div className="flex items-center justify-between mb-5">
                <h1 className="text-xl font-bold">题库配置 <span className="text-sm font-normal" style={{ color: 'var(--subtext)' }}>({sources.length}个答题源)</span></h1>
                <div className="flex gap-2">
                    <button className="ybtn" onClick={load} disabled={loading}>
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> 重载
                    </button>
                    <button className="ybtn" onClick={() => add('AI')}><Plus size={14} /> 添加AI源</button>
                    <button className="ybtn" onClick={() => add('')}><Plus size={14} /> 添加API源</button>
                    <button className="ybtn ybtn-primary" onClick={save}><Save size={14} /> 保存</button>
                </div>
            </div>

            <div className="ycard p-4 mb-4">
                <div className="text-xs mb-1.5" style={{ color: 'var(--subtext)' }}>多源顺序调用(留空=按列表顺序; 本地题库缓存总是优先)</div>
                <input className="yinput" value={order} onChange={e => setOrder(e.target.value)}
                    placeholder="如: 本地题库,AI,APIQUE" />
            </div>

            <div className="space-y-3">
                {sources.map((s, i) => (
                    <div key={i} className="ycard p-4">
                        <div className="flex items-center gap-2 mb-3">
                            <Database size={14} style={{ color: 'var(--primary)' }} />
                            <span className="text-sm font-medium">答题源 #{i + 1}</span>
                            <span className="flex-1" />
                            <label className="text-xs flex items-center gap-1" style={{ color: 'var(--subtext)' }}>
                                <input type="checkbox" checked={!!s.enable}
                                    onChange={e => upd(i, 'enable', e.target.checked ? 1 : 0)} /> 启用
                            </label>
                            <button className="ybtn ybtn-danger py-1 px-2 text-xs"
                                onClick={() => setSources(sources.filter((_, j) => j !== i))}>
                                <Trash2 size={12} />
                            </button>
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-xs">
                            <div>
                                <div style={{ color: 'var(--subtext)' }}>名称</div>
                                <input className="yinput mt-1" value={s.name || ''} onChange={e => upd(i, 'name', e.target.value)} />
                            </div>
                            <div>
                                <div style={{ color: 'var(--subtext)' }}>类型</div>
                                <select className="yselect mt-1" value={s.type || ''} onChange={e => upd(i, 'type', e.target.value)}>
                                    {TYPES.map(t => <option key={t} value={t}>{t || '默认(API)'}</option>)}
                                </select>
                            </div>
                            <div>
                                <div style={{ color: 'var(--subtext)' }}>Token/Key</div>
                                <input className="yinput mt-1" type="password" value={s.token || ''} onChange={e => upd(i, 'token', e.target.value)} />
                            </div>
                            <div>
                                <div style={{ color: 'var(--subtext)' }}>AI类型</div>
                                <select className="yselect mt-1" value={s.aiType || 'DEEPSEEK'} onChange={e => upd(i, 'aiType', e.target.value)}>
                                    {AI_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                                </select>
                            </div>
                            <div>
                                <div style={{ color: 'var(--subtext)' }}>模型</div>
                                <input className="yinput mt-1" value={s.model || ''} onChange={e => upd(i, 'model', e.target.value)} placeholder="deepseek-chat" />
                            </div>
                            <div>
                                <div style={{ color: 'var(--subtext)' }}>接口URL</div>
                                <input className="yinput mt-1" value={s.url || ''} onChange={e => upd(i, 'url', e.target.value)} placeholder="https://..." />
                            </div>
                        </div>
                    </div>
                ))}
                {sources.length === 0 && !loading && (
                    <div className="ycard p-10 text-center text-sm" style={{ color: 'var(--subtext)' }}>
                        暂无答题源 —— 右上角添加AI源/API源 (未配置时走本地题库缓存+学习通内置AI)
                    </div>
                )}
            </div>
            <div className="flex justify-end mt-4">
                <button className="ybtn ybtn-primary" onClick={save}><Save size={14} /> 保存答题源</button>
            </div>
        </div>
    )
}
