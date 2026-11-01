import React from 'react';

/* [V3.2.1] 全局错误边界
   背景: 之前任一页面渲染抛错(如 QuestionBank 的 t 遮蔽 TypeError)会导致
   整棵 React 树卸载 → 白屏且所有点击无响应(用户反馈"界面卡住/都卡")。
   这里做两层兜底: App 内容区(页面级, 保留侧边栏) + main.tsx(全屏级)。 */

type Props = { children: React.ReactNode; full?: boolean };
type State = { error: Error | null; info: string };

export default class ErrorBoundary extends React.Component<Props, State> {
    state: State = { error: null, info: '' };

    static getDerivedStateFromError(error: Error): Partial<State> {
        return { error };
    }

    componentDidCatch(error: Error, info: React.ErrorInfo) {
        // 控制台留证, 便于用户截图反馈
        // eslint-disable-next-line no-console
        console.error('[YatoriUI] 页面渲染异常:', error, info?.componentStack);
        this.setState({ info: String(info?.componentStack || '') });
    }

    private reset = () => {
        this.setState({ error: null, info: '' });
    };

    private reload = () => {
        try { location.reload(); } catch { /* ignore */ }
    };

    render() {
        const { error } = this.state;
        if (!error) return this.props.children;
        const full = !!this.props.full;
        return (
            <div style={{
                minHeight: full ? '100vh' : 320,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                padding: full ? 24 : 12
            }}>
                <div className="ycard p-6" style={{ maxWidth: 560, width: '100%' }}>
                    <div className="font-semibold text-base mb-2" style={{ color: '#f87171' }}>
                        页面渲染出错
                    </div>
                    <div className="text-xs mb-3" style={{ color: 'var(--subtext)' }}>
                        该页面发生了异常，已自动拦截以免整个界面卡死。可先点“重试”恢复；
                        若反复出现，请把下面的错误信息截图反馈。
                    </div>
                    <pre className="text-[11px] mb-4" style={{
                        whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                        maxHeight: 160, overflow: 'auto', opacity: .8,
                        background: 'rgba(0,0,0,.18)', padding: 10, borderRadius: 10
                    }}>{String(error?.message || error)}</pre>
                    <div className="flex gap-2">
                        <button className="ybtn ybtn-primary" onClick={this.reset}>重试</button>
                        <button className="ybtn" onClick={this.reload}>重新加载</button>
                        <button className="ybtn" onClick={() => { location.hash = '#/'; this.reset(); }}>
                            返回首页
                        </button>
                    </div>
                </div>
            </div>
        );
    }
}
