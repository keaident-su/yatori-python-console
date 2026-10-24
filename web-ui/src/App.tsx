import React, { useEffect, useState } from 'react';
import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
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
import { useT } from './i18n'
const NAV = [{
  to: '/',
  icon: LayoutDashboard,
  label: '仪表盘',
  end: true
}, {
  to: '/accounts',
  icon: Users,
  label: '账号管理'
}, {
  to: '/tasks',
  icon: PlayCircle,
  label: '任务控制'
}, {
  to: '/courses',
  icon: BookOpen,
  label: '课程进度'
}, {
  to: '/logs',
  icon: ScrollText,
  label: '日志中心'
}, {
  to: '/settings',
  icon: Settings,
  label: '全局设置'
}, {
  to: '/bank',
  icon: Database,
  label: '题库配置'
}, {
  to: '/about',
  icon: Info,
  label: '关于本项目'
}];
const THEMES = [{
  id: 'blue',
  label: '蓝白简洁',
  icon: Sun
}, {
  id: 'dark',
  label: '暗色霓虹',
  icon: Moon
}, {
  id: 'frost',
  label: '磨砂灰',
  icon: Cloud
}] as const;
export default function App() {
  const { t } = useT()
  const {
    theme,
    setTheme,
    toast,
    setAccounts
  } = useUI();
  const loc = useLocation();
  const [ver, setVer] = useState('');

  // 启动拉一次版本+账号缓存
  useEffect(() => {
    UI.about().then(d => setVer(d.version || '')).catch(() => {});
    UI.accounts().then(setAccounts).catch(() => {});
  }, []);
  return <div className="flex h-full">
            {/* 侧边栏 */}
            <aside className="w-56 shrink-0 flex flex-col border-r" style={{
      borderColor: 'var(--border)',
      background: 'var(--panel)',
      backdropFilter: 'blur(var(--panel-blur))'
    }}>
                <div className="px-5 pt-6 pb-4">
                    <div className="text-lg font-bold" style={{
          color: 'var(--primary)'
        }}>
                        Yatori UI
                    </div>
                    <div className="text-xs mt-1" style={{
          color: 'var(--subtext)'
        }}>{t("刷课系统 v")}{ver || '...'}
                    </div>
                </div>
                <nav className="flex-1 px-3 space-y-1 overflow-auto">
                    {NAV.map(n => <NavLink key={n.to} to={n.to} end={(n as any).end} className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all" style={({
          isActive
        }) => ({
          background: isActive ? 'var(--primary)' : 'transparent',
          color: isActive ? '#fff' : 'var(--text)',
          fontWeight: isActive ? 600 : 400
        })}>
                            <n.icon size={17} />
                            {n.label}
                        </NavLink>)}
                </nav>
                {/* 主题切换 */}
                <div className="p-3 border-t" style={{
        borderColor: 'var(--border)'
      }}>
                    <div className="text-xs mb-2 px-1" style={{
          color: 'var(--subtext)'
        }}>{t("界面主题")}</div>
                    <div className="flex gap-2">
                        {THEMES.map(t => <button key={t.id} title={t.label} onClick={() => setTheme(t.id)} className="flex-1 py-2 rounded-lg flex items-center justify-center" style={{
            border: '1px solid var(--border)',
            background: theme === t.id ? 'var(--primary)' : 'var(--panel-2)',
            color: theme === t.id ? '#fff' : 'var(--subtext)'
          }}>
                                <t.icon size={15} />
                            </button>)}
                    </div>
                </div>
            </aside>

            {/* 主区 */}
            <main className="flex-1 overflow-auto">
                <div className="max-w-[1200px] mx-auto p-6">
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
                </div>
            </main>

            {/* Toast */}
            {toast && <div className="fixed top-5 right-5 z-[80] px-4 py-3 rounded-xl text-sm shadow-2xl" style={{
      background: toast.type === 'ok' ? 'var(--ok)' : 'var(--danger)',
      color: '#fff'
    }}>
                    {toast.text}
                </div>}
        </div>;
}