import React, { useEffect, useState } from 'react';
import { Users, PlayCircle, CheckCircle2, Activity, RefreshCw } from 'lucide-react';
import { UI } from '../api';
import { useUI } from '../store';
import { useT } from '../i18n'
export default function Dashboard() {
  const { t } = useT()
  const {
    accounts,
    setAccounts,
    showToast
  } = useUI();
  const [loading, setLoading] = useState(false);
  const [rt, setRt] = useState<Record<string, any>>({});
  const load = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const accs = await UI.accounts();
      setAccounts(accs);
      // 运行中账号的实时状态
      const runMap: Record<string, any> = {};
      for (const a of accs.slice(0, 50)) {
        if (a.running) {
          try {
            const st = await UI.status(String(a.uid || a.account));
            runMap[String(a.uid || a.account)] = st.runtime || {};
          } catch {/* ignore */}
        }
      }
      setRt(runMap);
    } catch (e: any) {
      if (!silent) showToast(e.message, 'err');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
    const t = setInterval(() => load(true), 10000);
    return () => clearInterval(t);
  }, []);
  const total = accounts.length;
  const running = accounts.filter((a: any) => a.running).length;
  const platforms = Array.from(new Set(accounts.map((a: any) => a.platformType || a.platform_type || '?')));
  const Stat = ({
    icon: I,
    label,
    value,
    color
  }: any) => <div className="ycard p-5 flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{
      background: `color-mix(in srgb, ${color} 15%, transparent)`,
      color
    }}>
                <I size={22} />
            </div>
            <div>
                <div className="text-2xl font-bold">{value}</div>
                <div className="text-xs" style={{
        color: 'var(--subtext)'
      }}>{label}</div>
            </div>
        </div>;
  return <div>
            <div className="flex items-center justify-between mb-5">
                <h1 className="text-xl font-bold">{t("仪表盘")}</h1>
                <button className="ybtn" onClick={() => load()} disabled={loading}>
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{t("刷新")}</button>
            </div>

            <div className="grid grid-cols-3 gap-4 mb-6">
                <Stat icon={Users} label={t("账号总数")} value={total} color="var(--primary)" />
                <Stat icon={PlayCircle} label={t("运行中")} value={running} color="var(--ok)" />
                <Stat icon={CheckCircle2} label={t("平台种类")} value={platforms.length} color="var(--warn)" />
            </div>

            <div className="ycard p-5">
                <div className="flex items-center gap-2 mb-4">
                    <Activity size={16} style={{
          color: 'var(--primary)'
        }} />
                    <span className="font-semibold">{t("运行中的账号")}</span>
                    <span className="text-xs" style={{
          color: 'var(--subtext)'
        }}>{t("(10秒自动刷新)")}</span>
                </div>
                {running === 0 && <div className="text-sm py-6 text-center" style={{
        color: 'var(--subtext)'
      }}>{t("暂无运行中的账号 —— 去「任务控制」启动刷课，或「账号管理」添加账号")}</div>}
                <div className="space-y-2">
                    {accounts.filter((a: any) => a.running).map((a: any) => {
          const uid = String(a.uid || a.account);
          const r = rt[uid] || {};
          return <div key={uid} className="ycard-2 p-3 flex items-center justify-between text-sm">
                                <div className="flex items-center gap-3">
                                    <span className="ytag ytag-run">{t("运行中")}</span>
                                    <span className="font-medium">{a.remarkName || a.account}</span>
                                    <span style={{
                color: 'var(--subtext)'
              }}>{a.platformType || ''}</span>
                                </div>
                                <div className="text-xs" style={{
              color: 'var(--subtext)'
            }}>
                                    {r.stage || r.task || t("初始化中...")}
                                    {r.exam ? ` | 考试: ${r.exam}` : ''}
                                </div>
                            </div>;
        })}
                </div>
            </div>
        </div>;
}