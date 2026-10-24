/* [V3.0.11] 轻量 i18n 引擎(运行时插拔语言包)
 * 语言包目录(运行时): assets/i18n/{lang}.json
 * 结构: {"_meta":{"name","nativeName","rtl"},"ui":{"中文原文":"译文"},"server":{...}}
 * 设计: key=中文原文(改造量最小); 缺译自动回退中文; 内置zh-CN/en-US保底。
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import zhCN from './locales/zh-CN.json'
import enUS from './locales/en-US.json'

type Pack = { _meta?: any; ui?: Record<string, string>; server?: Record<string, string> }
const BUILTIN: Record<string, Pack> = { 'zh-CN': zhCN as any, 'en-US': enUS as any }
const BUILTIN_META = [
    { lang: 'zh-CN', name: 'Simplified Chinese', nativeName: '简体中文', rtl: 0 },
    { lang: 'en-US', name: 'English', nativeName: 'English', rtl: 0 },
]
const LS_KEY = 'yatori_lang'

function detectLang(list: any[]): string {
    try {
        const saved = localStorage.getItem(LS_KEY)
        if (saved && list.some((x: any) => x.lang === saved)) return saved
        const nav = (navigator.language || 'en-US').toLowerCase()
        const exact = list.find((x: any) => x.lang.toLowerCase() === nav)
        if (exact) return exact.lang
        const pref = list.find((x: any) => x.lang.toLowerCase().split('-')[0] === nav.split('-')[0])
        if (pref) return pref.lang
    } catch { }
    return 'en-US'
}

const I18nCtx = createContext<any>(null)

export function I18nProvider({ children }: any) {
    const [langs, setLangs] = useState<any[]>(BUILTIN_META)
    const [lang, setLangState] = useState<string>(() => detectLang(BUILTIN_META))
    const [pack, setPack] = useState<Pack>(BUILTIN['zh-CN'])

    // 初始化: 运行时语言列表(目录扫描) 合并内置
    useEffect(() => {
        (async () => {
            let list = BUILTIN_META
            try {
                const remote: any = await api('/ui/api/i18n/list')
                if (Array.isArray(remote) && remote.length) {
                    const map: Record<string, any> = {}
                    for (const m of [...BUILTIN_META, ...remote]) map[m.lang] = { ...(map[m.lang] || {}), ...m }
                    list = Object.values(map)
                }
            } catch { }
            setLangs(list)
            setLangState(detectLang(list))
        })()
    }, [])

    // 语言变化: 加载语言包(内置+运行时合并) + html lang/dir
    useEffect(() => {
        let alive = true
            ; (async () => {
                let p: Pack | null = BUILTIN[lang] || null
                try {
                    const remote: any = await api('/ui/api/i18n/' + encodeURIComponent(lang))
                    if (remote && typeof remote === 'object') {
                        p = {
                            _meta: { ...((p && p._meta) || {}), ...(remote._meta || {}) },
                            ui: { ...((p && p.ui) || {}), ...(remote.ui || {}) },
                            server: { ...((p && p.server) || {}), ...(remote.server || {}) },
                        }
                    }
                } catch { }
                if (!p) p = BUILTIN['zh-CN']
                if (!alive) return
                setPack(p || {})
                const meta = langs.find((x: any) => x.lang === lang)
                document.documentElement.setAttribute('lang', lang)
                document.documentElement.setAttribute('dir', meta && meta.rtl ? 'rtl' : 'ltr')
            })()
        return () => { alive = false }
    }, [lang, langs])

    const setLang = useCallback(async (l: string) => {
        try { localStorage.setItem(LS_KEY, l) } catch { }
        setLangState(l)
        // 持久化到 config.yaml setting.i18n.lang(失败不影响使用)
        try { await api('/ui/api/setting', { method: 'POST', body: { i18n: { lang: l } } }) } catch { }
    }, [])

    const t = useCallback((zhText: string) => {
        const ui = (pack && pack.ui) || {}
        const v = ui[zhText]
        return (typeof v === 'string' && v) ? v : zhText
    }, [pack])

    const value = useMemo(() => ({
        lang, langs, setLang, t,
        fmtDate: (d?: any) => {
            try { return new Intl.DateTimeFormat(lang, { dateStyle: 'medium', timeStyle: 'medium' }).format(d ? new Date(d) : new Date()) }
            catch { return String(d || '') }
        },
        fmtNum: (n: any) => { try { return new Intl.NumberFormat(lang).format(n) } catch { return String(n) } },
    }), [lang, langs, pack, t, setLang])

    return <I18nCtx.Provider value={value}>{children}</I18nCtx.Provider>
}

const FALLBACK = {
    t: (s: string) => s, lang: 'zh-CN', langs: BUILTIN_META,
    setLang: (_l: string) => { }, fmtDate: (d?: any) => String(d || ''),
    fmtNum: (n: any) => String(n),
}

export function useT() {
    const ctx = useContext(I18nCtx)
    return ctx || FALLBACK
}
