import React, { useEffect, useState } from 'react';
import { Play, Square, RefreshCw, Zap } from 'lucide-react';
import { UI } from '../api';
import { useUI } from '../store';
import { useT } from '../i18n'
export default function Tasks() {
  const { t } = useT()
  const {
    accounts,
    setAccounts,
    showToast
  } = useUI();
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
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
    // [V3.0.8] 每5秒静默刷新运行状态(启动/停止后状态可见、可持续刷新)
    const t = setInterval(() => {
      UI.accounts().then((d: any) => setAccounts(d)).catch(() => {});
    }, 5000);
    return () => clearInterval(t);
  }, []);
  const act = async (uid: string, kind: 'start' | 'stop') => {
    setBusy(b => ({
      ...b,
      [uid]: true
    }));
    try {
      if (kind === 'start') await UI.start(uid);else await UI.stop(uid);
      showToast(kind === 'start' ? t("已启动刷课") : t("已发送停止指令"));
      setTimeout(load, 1200);
    } catch (e: any) {
      showToast(e.message, 'err');
    } finally {
      setBusy(b => ({
        ...b,
        [uid]: false
      }));
    }
  };
  const startAll = async () => {
    const idle = accounts.filter((a: any) => !a.running);
    if (!idle.length) return showToast(t("没有空闲账号"), 'err');
    if (!confirm(`确认批量启动 ${idle.length} 个空闲账号?`)) return;
    for (const a of idle) {
      try {
        await UI.start(String(a.uid || a.account));
      } catch {}
    }
    showToast(`已批量启动 ${idle.length} 个账号`);
    setTimeout(load, 1500);
  };
  return <div>
            <div className="flex items-center justify-between mb-5">
                <h1 className="text-xl font-bold">{t("任务控制")}</h1>
                <div className="flex gap-2">
                    <button className="ybtn" onClick={load} disabled={loading}>
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{t("刷新")}</button>
                    <button className="ybtn ybtn-primary" onClick={startAll}>
                        <Zap size={14} />{t("一键启动全部空闲")}</button>
                </div>
            </div>

            <div className="space-y-2">
                {accounts.map((a: any) => {
        const uid = String(a.uid || a.account);
        return <div key={uid} className="ycard p-4 flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <span className={a.running ? 'ytag ytag-run' : 'ytag'}
                                    style={a.resting ? { background: '#fff7e6', color: '#ad6800', borderColor: '#ffe58f' } : undefined}>
                                    {a.resting
                                        ? ('🌙 ' + t("夜间休息") + (a.restResumeHm ? (' · ' + t("预计") + ' ' + a.restResumeHm + ' ' + t("自动恢复")) : ''))
                                        : (a.running ? t("● 运行中") : t("○ 空闲"))}
                                </span>
                                <div>
                                    <div className="font-medium text-sm">{a.remarkName || a.account}</div>
                                    <div className="text-xs" style={{
                color: 'var(--subtext)'
              }}>
                                        {a.platformType || a.platform_type} | {a.account}
                                    </div>
                                </div>
                            </div>
                            <div className="flex gap-2">
                                <button className="ybtn ybtn-primary py-1.5 px-4 text-xs" disabled={a.running || busy[uid]} onClick={() => act(uid, 'start')}>
                                    <Play size={13} />{t("启动")}</button>
                                <button className="ybtn ybtn-danger py-1.5 px-4 text-xs" disabled={!a.running || busy[uid]} onClick={() => act(uid, 'stop')}>
                                    <Square size={13} />{t("停止")}</button>
                            </div>
                        </div>;
      })}
                {accounts.length === 0 && <div className="ycard p-10 text-center text-sm" style={{
        color: 'var(--subtext)'
      }}>{t("暂无账号，请先到「账号管理」添加")}</div>}
            </div>
        </div>;
}