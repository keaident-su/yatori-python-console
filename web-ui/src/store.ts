/* 全局状态(zustand, 2026-10-23) */
import { create } from 'zustand'

export type ThemeId = 'blue' | 'dark' | 'frost'

interface UIState {
  theme: ThemeId
  bgUrl: string          // 自定义背景图片URL(本地图/网络图片API)
  accounts: any[]
  loading: boolean
  toast: { text: string; type: 'ok' | 'err' } | null
  setTheme: (t: ThemeId) => void
  setBgUrl: (u: string) => void
  setAccounts: (a: any[]) => void
  setLoading: (b: boolean) => void
  showToast: (text: string, type?: 'ok' | 'err') => void
}

const saved = (k: string, d: string) => {
  try { return localStorage.getItem(k) || d } catch { return d }
}

export const useUI = create<UIState>((set) => ({
  theme: (saved('yui_theme', 'blue') as ThemeId),
  bgUrl: saved('yui_bg', ''),
  accounts: [],
  loading: false,
  toast: null,
  setTheme: (t) => {
    set({ theme: t })
    try { localStorage.setItem('yui_theme', t) } catch {}
    applyTheme(t, useUI.getState().bgUrl)
  },
  setBgUrl: (u) => {
    set({ bgUrl: u })
    try { localStorage.setItem('yui_bg', u) } catch {}
    applyTheme(useUI.getState().theme, u)
  },
  setAccounts: (a) => set({ accounts: a }),
  setLoading: (b) => set({ loading: b }),
  showToast: (text, type = 'ok') => {
    set({ toast: { text, type } })
    setTimeout(() => set({ toast: null }), 3200)
  },
}))

export function applyTheme(t: ThemeId, bgUrl: string) {
  const el = document.documentElement
  el.setAttribute('data-theme', t === 'blue' ? '' : t)
  if (bgUrl) {
    el.style.setProperty('--bg-image', `url("${bgUrl}")`)
    // 有自定义背景时面板加毛玻璃保证可读
    if (t === 'blue') {
      el.style.setProperty('--panel', 'rgba(255,255,255,0.82)')
      el.style.setProperty('--panel-blur', '12px')
    }
  } else {
    el.style.setProperty('--bg-image', 'none')
    if (t === 'blue') {
      el.style.setProperty('--panel', '#ffffff')
      el.style.setProperty('--panel-blur', '0px')
    }
  }
}
