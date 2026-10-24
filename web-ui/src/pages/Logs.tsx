import React, { useEffect, useRef, useState } from 'react';
import { RefreshCw, ScrollText } from 'lucide-react';
import { UI } from '../api';
import { useUI } from '../store';
import { useT } from '../i18n'

/* [V3.1.2] 日志中心(规范增强版):
   · 逐行渲染(不再整串 JSON); 主条目单行不折行(横向滚动), 附属行(4空格缩进)灰显
   · 级别着色: ERROR/FATAL 红, WARN 黄, DEBUG 灰
   · 悬停显示全文; desc(最新在前)自动滚顶 */
const MAIN_RE = /^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}/;
const LVL_RE = /\] \[(DEBUG|INFO|WARN|WARNING|ERROR|FATAL|BOLD_RED)\] \[/;

function levelOf(s: string): string {
    const m = s.match(LVL_RE);
    if (!m) return '';
    return m[1] === 'WARNING' ? 'WARN' : m[1];
}

function colorOf(lv: string): string | undefined {
    if (lv === 'ERROR' || lv === 'FATAL' || lv === 'BOLD_RED') return '#f87171';
    if (lv === 'WARN') return '#fbbf24';
    if (lv === 'DEBUG') return '#9ca3af';
    return undefined;
}

export default function Logs() {
    const { t } = useT()
    const {
        accounts,
        showToast
    } = useUI();
    const [acct, setAcct] = useState('');
    const [date, setDate] = useState('');
    const [lines, setLines] = useState<string[]>([]);
    const [auto, setAuto] = useState(true);
    const [loading, setLoading] = useState(false);
    const boxRef = useRef<HTMLDivElement>(null);
    const load = async (silent = false) => {
        if (!silent) setLoading(true);
        try {
            const raw: any = await UI.logTail(acct, date, 400);
            // [V3.1.2] 双层兼容: raw 可能是 {lines...} 或 {code,message,data:{lines...}}
            const d: any = (raw && Array.isArray(raw.lines)) ? raw
                : (raw && raw.data && Array.isArray(raw.data.lines) ? raw.data : {});
            const ls: string[] = Array.isArray(d.lines) ? d.lines : [];
            setLines(ls);
            const desc = !d.order || d.order === 'desc';
            requestAnimationFrame(() => {
                const el = boxRef.current;
                if (el) el.scrollTop = desc ? 0 : el.scrollHeight;
            });
        } catch (e: any) {
            if (!silent) showToast(e.message, 'err');
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => {
        load();
    }, [acct, date]);
    useEffect(() => {
        if (!auto) return;
        const timer = setInterval(() => load(true), 5000);
        return () => clearInterval(timer);
    }, [auto, acct, date]);
    return <div className="flex flex-col h-[calc(100vh-120px)]">
        <div className="flex items-center justify-between mb-4">
            <h1 className="text-xl font-bold">{t("日志中心")}</h1>
            <div className="flex items-center gap-2">
                <select className="yselect w-48" value={acct} onChange={e => setAcct(e.target.value)}>
                    <option value="">{t("全部账号")}</option>
                    {accounts.map((a: any) => <option key={String(a.uid || a.account)} value={String(a.account || a.uid)}>
                        {a.remarkName || a.account}
                    </option>)}
                </select>
                <input className="yinput w-36" value={date} placeholder={t("日期 如2026-10-23")} onChange={e => setDate(e.target.value)} />
                <label className="flex items-center gap-1 text-xs cursor-pointer" style={{
                    color: 'var(--subtext)'
                }}>
                    <input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} />{t("自动刷新(5s)")}
                </label>
                <button className="ybtn" onClick={() => load()} disabled={loading}>
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                </button>
            </div>
        </div>

        <div ref={boxRef} className="ycard flex-1 overflow-auto py-2 font-mono text-xs leading-5"
            style={{ color: 'var(--text)' }}>
            {lines.length === 0 ? <div className="px-4" style={{
                color: 'var(--subtext)'
            }}>
                <ScrollText size={14} className="inline mr-2" />{t("暂无日志（选择账号查看其专属日志，或刷课启动后自动产生）")}</div>
                : lines.map((s, i) => {
                    const main = MAIN_RE.test(s);
                    if (!main) {
                        // 附属行(堆栈等): 保留原缩进, 灰显, 允许折行
                        return <div key={i} title={s} className="px-4" style={{
                            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                            color: 'var(--subtext)', background: 'rgba(127,127,127,0.06)'
                        }}>{s || ' '}</div>;
                    }
                    const lv = levelOf(s);
                    return <div key={i} title={s} className="px-4 hover:bg-[rgba(127,127,127,0.08)]" style={{
                        whiteSpace: 'pre',
                        color: colorOf(lv)
                    }}>{s}</div>;
                })}
        </div>
    </div>;
}
