import React, { useEffect, useState } from 'react';
import { Routes, Route, NavLink } from 'react-router-dom';
import { LayoutDashboard, Users, PlayCircle, BookOpen, ScrollText, Settings, Database, Info, Sun, Moon, Cloud } from 'lucide-react';
import { useUI } from './store';
import { UI } from './api';
import Dashboard from './pages/Dashboard';
import Accounts from './pages/Accounts';
import Tasks from './pages/Tasks';
import Courses from './pages/Courses';
import Logs from './pages/Logs';
import SettingsPage from './pages/Settings';
import QuestionBank from './pages/QuestionBank';
import About from './pages/About';
import ErrorBoundary from './ErrorBoundary';
import SponsorBanner from './components/SponsorBanner';
import { useT } from './i18n'

/* [V3.2.0 Liquid Glass] 导航: 分组 + 彩色 icon 胶囊(参考 iOS 图标块) */
const NAV_MAIN = [{
  to: '/', icon: LayoutDashboard, label: '仪表盘', end: true, chip: ['#6ea1ff', '#3f6fe0']
}, {
  to: '/accounts', icon: Users, label: '账号管理', chip: ['#6fd8a2', '#2e9e6b']
}, {
  to: '/tasks', icon: PlayCircle, label: '任务控制', chip: ['#ffc46b', '#ef8f1f']
}, {
  to: '/courses', icon: BookOpen, label: '课程进度', chip: ['#c3a1ff', '#8a5cf0']
}, {
  to: '/bank', icon: Database, label: '题库配置', chip: ['#5fe0d6', '#1aa7a1']
}];
const NAV_SUB = [{
  to: '/logs', icon: ScrollText, label: '日志中心', chip: ['#93aee6', '#4c6cb3']
}, {
  to: '/settings', icon: Settings, label: '全局设置', chip: ['#a3aec4', '#5d6b85']
}, {
  to: '/about', icon: Info, label: '关于本项目', chip: ['#ff9db1', '#e5546f']
}];
const THEMES = [{
  id: 'blue', label: '浅色玻璃', icon: Sun
}, {
  id: 'dark', label: '深色玻璃', icon: Moon
}, {
  id: 'frost', label: '磨砂灰', icon: Cloud
}] as const;

const PLAT_NAME: Record<string, string> = {
  XUEXITONG: '学习通', ZHIHUISHU: '智慧树', QSXT: '青书学堂', YINGHUA: '英华',
  WEBAN: '安全微伴', ENAEA: '学习公社', CQIE: '重庆工程', KETANGX: '课堂派',
  WELEARN: 'WeLearn', ICVE: '智慧职教', HQKJ: '海旗科技', DZYX: '大众云学',
};

export default function App() {
  const { t } = useT()
  const {
    theme,
    setTheme,
    toast,
    accounts,
    setAccounts
  } = useUI();
  const [ver, setVer] = useState('');

  // 启动拉一次版本+账号缓存
  useEffect(() => {
    UI.about().then(d => setVer(d.version || '')).catch(() => { });
    UI.accounts().then(setAccounts).catch(() => { });
    const timer = setInterval(() => {
      UI.accounts().then(setAccounts).catch(() => { });
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  const runningList = (accounts || []).filter((a: any) => a && a.running);
  const running = runningList.length;
  const total = (accounts || []).length;
  const pct = total > 0 ? Math.round(running / total * 100) : 0;
  const mainPlat = runningList[0]
    ? (PLAT_NAME[runningList[0].platformType || runningList[0].accountType] || runningList[0].platformType || runningList[0].accountType || '-')
    : '-';

  const navItem = (n: any) => <NavLink key={n.to} to={n.to} end={n.end}
    className={({ isActive }) => 'ynav-item' + (isActive ? ' active' : '')}>
    <span className="ychip" style={{
      ['--chip-a' as any]: n.chip[0], ['--chip-b' as any]: n.chip[1]
    }}>
      <n.icon size={14} />
    </span>
    {t(n.label)}
  </NavLink>;

  return <div className="flex h-full">
    {/* 侧边栏(液态玻璃列) */}
    <aside className="yside">
      {/* 品牌 */}
      <div className="flex items-center gap-3 px-4 pt-5 pb-3">
        <div style={{
          width: 38, height: 38, borderRadius: 12, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'linear-gradient(150deg, color-mix(in srgb, var(--primary) 78%, #fff), var(--primary))',
          boxShadow: 'inset 0 1px 0 rgba(255,255,255,.55), 0 8px 20px color-mix(in srgb, var(--primary) 40%, transparent)'
        }}>
          <Cloud size={20} color="#fff" />
        </div>
        <div>
          <div className="text-[15px] font-bold leading-tight">Yatori</div>
          <div className="text-[11px]" style={{ color: 'var(--subtext)' }}>
            {t("刷课系统 v")}{ver || '...'}
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-auto pb-2">
        <div className="ynav-group">{t("控制台")}</div>
        {NAV_MAIN.map(navItem)}
        <div className="ynav-group" style={{ paddingTop: 14 }}>{t("其他")}</div>
        {NAV_SUB.map(navItem)}
      </nav>

      {/* 底部运行状态卡 */}
      <div className="ystatus">
        <div className="flex items-center gap-2 text-[12px]">
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: running > 0 ? 'var(--ok)' : 'var(--subtext)',
            boxShadow: running > 0 ? '0 0 8px var(--ok)' : 'none'
          }} />
          <span style={{ color: 'var(--subtext)' }}>
            {running > 0 ? t("任务运行中") : t("空闲")}
          </span>
          <span className="ml-auto font-semibold">{mainPlat}</span>
        </div>
        <div className="text-[11px] mt-2 flex justify-between" style={{ color: 'var(--subtext)' }}>
          <span>{t("运行中")} {running}/{total}</span>
          <span>{pct}%</span>
        </div>
        <div className="yprogress mt-1.5"><i style={{ width: pct + '%' }} /></div>
      </div>

      {/* 主题快捷切换 */}
      <div className="px-3 pb-3">
        <div className="text-[11px] mb-1.5 px-1" style={{ color: 'var(--subtext)' }}>{t("界面主题")}</div>
        <div className="yseg w-full" style={{ display: 'flex' }}>
          {THEMES.map(th => <button key={th.id} title={t(th.label)}
            onClick={() => setTheme(th.id)}
            className={theme === th.id ? 'on' : ''} style={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
            <th.icon size={14} />
          </button>)}
        </div>
      </div>
    </aside>

    {/* 主区 */}
    <main className="flex-1 overflow-auto">
      <div className="max-w-[1240px] mx-auto p-6 lg:p-8">
        {/* [赞助/赞赏] 开屏赞助横幅 + 微信赞赏码展示 */}
        <SponsorBanner />
        {/* [V3.2.1] 页面级错误边界: 单页崩溃不影响侧边栏与其他页面 */}
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/courses" element={<Courses />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/bank" element={<QuestionBank />} />
            <Route path="/about" element={<About />} />
          </Routes>
        </ErrorBoundary>
      </div>
    </main>

    {/* Toast(玻璃) */}
    {toast && <div className="ytoast" style={{
      color: toast.type === 'ok' ? 'var(--text)' : '#fff',
      background: toast.type === 'ok'
        ? 'color-mix(in srgb, var(--panel-3) 82%, transparent)'
        : 'linear-gradient(150deg, color-mix(in srgb, var(--danger) 82%, #fff), var(--danger))'
    }}>
      {toast.text}
    </div>}
  </div>;
}
