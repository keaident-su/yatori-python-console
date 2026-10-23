import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import './theme.css'
import { applyTheme, useUI, applyRandomBgApi } from './store'

const _st = useUI.getState()
applyTheme(_st.theme, _st.bgUrl)
// [2026-10-24] 随机图片API模式: 每次启动自动拉取一张新背景(防缓存参数)
if (_st.bgMode === 'api' && _st.bgApi) {
  applyRandomBgApi(_st.bgApi)
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
)
