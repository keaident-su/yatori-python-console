/* API层(2026-10-23): 统一fetch封装 + token + 错误处理 */
const qs = new URLSearchParams(location.search)
const TOKEN = qs.get('token') || localStorage.getItem('yui_token') || ''
if (qs.get('token')) localStorage.setItem('yui_token', TOKEN)

export async function api<T = any>(path: string, opts: {
  method?: string; body?: any; timeout?: number
} = {}): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), opts.timeout ?? 60000)
  try {
    const res = await fetch(path, {
      method: opts.method || 'GET',
      headers: {
        'Content-Type': 'application/json',
        'X-UI-Token': TOKEN,
      },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: ctrl.signal,
    })
    const data = await res.json()
    if (data.code !== 200) throw new Error(data.msg || ('HTTP ' + res.status))
    // 统一解包: 返回 data 字段(各页面直接拿到业务数据)
    return (data.data !== undefined ? data.data : data) as T
  } finally {
    clearTimeout(timer)
  }
}

export const UI = {
  ping: () => api('/ui/api/ping'),
  accounts: () => api<any[]>('/ui/api/accounts'),
  addAccount: (b: any) => api('/ui/api/account/add', { method: 'POST', body: b }),
  delAccount: (uid: string) => api('/ui/api/account/delete', { method: 'POST', body: { uid } }),
  updAccount: (b: any) => api('/ui/api/account/update', { method: 'POST', body: b }),
  loginCheck: (b: any) => api('/ui/api/account/logincheck', { method: 'POST', body: b }),
  start: (uid: string) => api('/ui/api/task/start', { method: 'POST', body: { uid } }),
  stop: (uid: string) => api('/ui/api/task/stop', { method: 'POST', body: { uid } }),
  status: (uid: string) => api<any>(`/ui/api/task/status/${uid}`),
  courses: (uid: string, force = false) => api<any>(`/ui/api/courses/${uid}${force ? '?force=1' : ''}`, { timeout: 120000 }),
  rtstatus: (uid: string) => api<any>(`/ui/api/rtstatus/${uid}`),
  logAccounts: () => api<any>('/ui/api/logs/accounts'),
  logTail: (account = '', date = '', lines = 300) =>
    api<any>(`/ui/api/logs/tail?account=${encodeURIComponent(account)}&date=${encodeURIComponent(date)}&lines=${lines}`),
  getSetting: () => api<any>('/ui/api/setting'),
  saveSetting: (b: any) => api('/ui/api/setting', { method: 'POST', body: b }),
  answerSources: () => api<any>('/ui/api/answersources'),
  saveAnswerSources: (b: any) => api('/ui/api/answersources', { method: 'POST', body: b }),
  uploadBg: (dataUrl: string) => api<any>('/ui/api/bg/upload', { method: 'POST', body: { dataUrl } }),
  about: () => api<any>('/ui/api/about'),
}
