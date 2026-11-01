/* 全局状态(zustand) —— [V3.2.0] Liquid Glass 基底: 模式/主副色/壁纸/背景图 */
import { create } from 'zustand'

export type ThemeId = 'blue' | 'dark' | 'frost'
export type BgMode = '' | 'upload' | 'url' | 'api'
export type WallpaperId = 'aurora' | 'night' | 'peach' | 'mint' | 'mono'

/* 主题配色预设(点选即同时更换主色+副色, 对齐参考图的圆形色块) */
export const COLOR_PRESETS: { id: string; name: string; c: string; a: string }[] = [
  { id: 'iosblue', name: 'iOS 蓝', c: '#5b8cff', a: '#9b6bff' },
  { id: 'starry', name: '星夜紫', c: '#9b6bff', a: '#ff6b9d' },
  { id: 'sakura', name: '樱粉', c: '#ff6b9d', a: '#ff9f5b' },
  { id: 'sunset', name: '暖橙', c: '#ff9f5b', a: '#ffd45b' },
  { id: 'mint', name: '薄荷', c: '#2ecc9b', a: '#5b8cff' },
]

/* 壁纸预设(纯 CSS 渐变, 无需内置图片资源) */
export const WALLPAPERS: { id: WallpaperId; name: string; css: string }[] = [
  {
    id: 'aurora', name: '极光',
    css: 'radial-gradient(1100px 760px at 10% 6%, rgba(122,168,255,.85) 0%, transparent 62%),' +
      'radial-gradient(960px 700px at 92% 10%, rgba(186,154,255,.78) 0%, transparent 58%),' +
      'radial-gradient(900px 860px at 74% 96%, rgba(120,235,205,.68) 0%, transparent 60%),' +
      'linear-gradient(158deg, #eef4ff 0%, #f7f2ff 46%, #e9faf3 100%)',
  },
  {
    id: 'night', name: '夜幕',
    css: 'radial-gradient(1100px 760px at 12% 8%, rgba(46,92,190,.55) 0%, transparent 62%),' +
      'radial-gradient(900px 700px at 90% 14%, rgba(104,66,190,.48) 0%, transparent 58%),' +
      'radial-gradient(860px 820px at 72% 96%, rgba(20,120,120,.40) 0%, transparent 62%),' +
      'linear-gradient(160deg, #0a1120 0%, #0d1428 48%, #0a1a1c 100%)',
  },
  {
    id: 'peach', name: '蜜桃',
    css: 'radial-gradient(1000px 720px at 8% 8%, rgba(255,178,150,.85) 0%, transparent 62%),' +
      'radial-gradient(900px 680px at 94% 12%, rgba(255,150,190,.72) 0%, transparent 58%),' +
      'radial-gradient(860px 800px at 70% 96%, rgba(255,214,140,.62) 0%, transparent 62%),' +
      'linear-gradient(160deg, #fff4ee 0%, #fff0f5 48%, #fff8ea 100%)',
  },
  {
    id: 'mint', name: '薄荷',
    css: 'radial-gradient(1000px 720px at 10% 8%, rgba(130,235,200,.78) 0%, transparent 62%),' +
      'radial-gradient(900px 680px at 92% 12%, rgba(120,190,255,.68) 0%, transparent 58%),' +
      'radial-gradient(860px 800px at 70% 96%, rgba(190,255,220,.66) 0%, transparent 62%),' +
      'linear-gradient(160deg, #eefbf6 0%, #eff8ff 48%, #f2fff8 100%)',
  },
  {
    id: 'mono', name: '极简',
    css: 'radial-gradient(1000px 700px at 8% 6%, rgba(214,222,238,.95) 0%, transparent 62%),' +
      'radial-gradient(900px 680px at 94% 12%, rgba(226,230,240,.95) 0%, transparent 58%),' +
      'linear-gradient(160deg, #f2f4f8 0%, #e9edf4 50%, #f4f6fa 100%)',
  },
]

interface UIState {
  theme: ThemeId
  primary: string
  accent: string
  wallpaper: WallpaperId
  bgUrl: string          // 当前生效背景图片URL(本地图/网络图片API)
  bgMode: BgMode         // 背景来源: ''无 / upload本地上传 / url固定URL / api随机图片API
  bgApi: string          // 随机图片API地址(bgMode=api时使用)
  accounts: any[]
  loading: boolean
  toast: { text: string; type: 'ok' | 'err' } | null
  setTheme: (t: ThemeId) => void
  setPrimary: (c: string) => void
  setAccent: (c: string) => void
  setWallpaper: (w: WallpaperId) => void
  setPreset: (id: string) => void
  resetAppearance: () => void
  setBgUrl: (u: string) => void
  setBgMode: (m: BgMode) => void
  setBgApi: (u: string) => void
  setAccounts: (a: any[]) => void
  setLoading: (b: boolean) => void
  showToast: (text: string, type?: 'ok' | 'err') => void
}

const saved = (k: string, d: string) => {
  try { return localStorage.getItem(k) || d } catch { return d }
}
const save = (k: string, v: string) => {
  try { localStorage.setItem(k, v) } catch { }
}

export const useUI = create<UIState>((set) => ({
  theme: (saved('yui_theme', 'blue') as ThemeId),
  primary: saved('yui_primary', '#5b8cff'),
  accent: saved('yui_accent', '#9b6bff'),
  wallpaper: (saved('yui_wallpaper', 'aurora') as WallpaperId),
  bgUrl: saved('yui_bg', ''),
  bgMode: (saved('yui_bg_mode', '') as BgMode),
  bgApi: saved('yui_bg_api', ''),
  accounts: [],
  loading: false,
  toast: null,
  setTheme: (t) => {
    set({ theme: t })
    save('yui_theme', t)
    applyTheme(t, useUI.getState().bgUrl)
  },
  setPrimary: (c) => {
    set({ primary: c })
    save('yui_primary', c)
    applyTheme(useUI.getState().theme, useUI.getState().bgUrl)
  },
  setAccent: (c) => {
    set({ accent: c })
    save('yui_accent', c)
    applyTheme(useUI.getState().theme, useUI.getState().bgUrl)
  },
  setWallpaper: (w) => {
    set({ wallpaper: w })
    save('yui_wallpaper', w)
    applyTheme(useUI.getState().theme, useUI.getState().bgUrl)
  },
  setPreset: (id) => {
    const p = COLOR_PRESETS.find(x => x.id === id)
    if (!p) return
    set({ primary: p.c, accent: p.a })
    save('yui_primary', p.c)
    save('yui_accent', p.a)
    applyTheme(useUI.getState().theme, useUI.getState().bgUrl)
  },
  resetAppearance: () => {
    set({
      theme: 'blue', primary: '#5b8cff', accent: '#9b6bff',
      wallpaper: 'aurora', bgUrl: '', bgMode: '',
    })
    save('yui_theme', 'blue')
    save('yui_primary', '#5b8cff')
    save('yui_accent', '#9b6bff')
    save('yui_wallpaper', 'aurora')
    save('yui_bg', '')
    save('yui_bg_mode', '')
    applyTheme('blue', '')
  },
  setBgUrl: (u) => {
    set({ bgUrl: u })
    save('yui_bg', u)
    applyTheme(useUI.getState().theme, u)
  },
  setBgMode: (m) => {
    set({ bgMode: m })
    save('yui_bg_mode', m)
  },
  setBgApi: (u) => {
    set({ bgApi: u })
    save('yui_bg_api', u)
  },
  setAccounts: (a) => set({ accounts: a }),
  setLoading: (b) => set({ loading: b }),
  showToast: (text, type = 'ok') => {
    set({ toast: { text, type } })
    setTimeout(() => set({ toast: null }), 3200)
  },
}))

/** 随机图片API换一张: 拼接防缓存参数并应用 */
export function applyRandomBgApi(apiUrl: string) {
  if (!apiUrl) return
  const sep = apiUrl.includes('?') ? '&' : '?'
  const u = `${apiUrl}${sep}_r=${Date.now()}`
  useUI.getState().setBgUrl(u)
}

/** 应用外观: 模式 + 主副色 + 壁纸 + 自定义背景图(参数缺省则读 store) */
export function applyTheme(t: ThemeId, bgUrl: string,
  primary?: string, accent?: string, wallpaper?: string) {
  const el = document.documentElement
  const st = (() => { try { return useUI.getState() } catch { return null as any } })()
  el.setAttribute('data-theme', t === 'blue' ? '' : t)
  // 清除可能残留的行内变量(旧版兼容)
  el.style.removeProperty('--panel')
  el.style.removeProperty('--panel-blur')
  el.style.removeProperty('--bg-image')
  const p = primary || (st && st.primary)
  const a = accent || (st && st.accent)
  if (p) el.style.setProperty('--primary', p)
  if (a) el.style.setProperty('--accent', a)
  const wid = wallpaper || (st && st.wallpaper) || 'aurora'
  const wp = WALLPAPERS.find(w => w.id === wid) || WALLPAPERS[0]
  el.style.setProperty('--wallpaper', wp.css)
  if (bgUrl) el.style.setProperty('--bg-image', `url("${bgUrl}")`)
}
