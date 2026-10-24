/* [V3.0.11] 轻量 i18n 引擎 —— 支持 Minecraft MOD 风格语言包
 * 语言包(运行时): assets/i18n/{lang}.json, 文件名小写下划线(zh_cn/en_us/ja_jp...)
 * 结构(MC 风格): 顶层扁平 {"中文原文":"译文"}  (兼容旧的 {_meta/ui/server} 结构)
 * 设计: key=中文原文; 缺译自动回退中文; 丢文件即支持新语种。
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import zhCN from './locales/zh_cn.json'
import enUS from './locales/en_us.json'

type FlatPack = Record<string, string>
const BUILTIN: Record<string, FlatPack> = { zh_cn: zhCN as any, en_us: enUS as any }

// 内置语言元信息(MC 文件名 -> 显示名/原生名/方向); 未知语种自动用文件名兜底
const LANG_META: Record<string, any> = {
    zh_cn: { name: 'Simplified Chinese', nativeName: '简体中文', rtl: 0 },
    en_us: { name: 'English', nativeName: 'English', rtl: 0 },
    zh_tw: { name: 'Traditional Chinese', nativeName: '繁體中文', rtl: 0 },
    ja_jp: { name: 'Japanese', nativeName: '日本語', rtl: 0 },
    ko_kr: { name: 'Korean', nativeName: '한국어', rtl: 0 },
    ru_ru: { name: 'Russian', nativeName: 'Русский', rtl: 0 },
    ar_sa: { name: 'Arabic', nativeName: 'العربية', rtl: 1 },
    de_de: { name: 'German', nativeName: 'Deutsch', rtl: 0 },
    fr_fr: { name: 'French', nativeName: 'Français', rtl: 0 },
    es_es: { name: 'Spanish', nativeName: 'Español', rtl: 0 },
    pt_br: { name: 'Portuguese (BR)', nativeName: 'Português', rtl: 0 },
    it_it: { name: 'Italian', nativeName: 'Italiano', rtl: 0 },
    vi_vn: { name: 'Vietnamese', nativeName: 'Tiếng Việt', rtl: 0 },
    th_th: { name: 'Thai', nativeName: 'ไทย', rtl: 0 },
    tr_tr: { name: 'Turkish', nativeName: 'Türkçe', rtl: 0 },
    pl_pl: { name: 'Polish', nativeName: 'Polski', rtl: 0 },
    uk_ua: { name: 'Ukrainian', nativeName: 'Українська', rtl: 0 },
    nl_nl: { name: 'Dutch', nativeName: 'Nederlands', rtl: 0 },
    cs_cz: { name: 'Czech', nativeName: 'Čeština', rtl: 0 },
    sv_se: { name: 'Swedish', nativeName: 'Svenska', rtl: 0 },
}
const RTL_PREFIX = ['ar', 'he', 'fa', 'ur']

export function normLang(lang: string): string {
    return String(lang || '').trim().toLowerCase().replace(/-/g, '_')
}

function langMeta(lang: string) {
    const m = LANG_META[lang]
    if (m) return m
    const rtl = RTL_PREFIX.includes(lang.split('_')[0]) ? 1 : 0
    return { name: lang, nativeName: lang, rtl }
}

function detectLang(list: string[]): string {
    try {
        const saved = normLang(localStorage.getItem('yatori_lang') || '')
        if (saved && list.includes(saved)) return saved
        const nav = normLang(navigator.language || 'en_us')
        if (list.includes(nav)) return nav
        const pref = nav.split('_')[0]
        const hit = list.find(l => l.split('_')[0] === pref)
        if (hit) return hit
    } catch { }
    return 'en_us'
}

const I18nCtx = createContext<any>(null)

/** 兼容解析: MC 扁平包 或 旧 {ui,server,_meta} 结构 -> 扁平映射 */
function toFlat(d: any): FlatPack {
    if (!d || typeof d !== 'object') return {}
    if (d.ui || d.server || d._meta) {
        const out: FlatPack = {}
        for (const sec of ['ui', 'server']) {
            if (d[sec] && typeof d[sec] === 'object') {
                for (const k in d[sec]) if (typeof d[sec][k] === 'string') out[k] = d[sec][k]
            }
        }
        return out
    }
    const out: FlatPack = {}
    for (const k in d) {
        if (k.startsWith('_')) continue
        if (typeof d[k] === 'string') out[k] = d[k]
    }
    return out
}

export function I18nProvider({ children }: any) {
    const [langs, setLangs] = useState<string[]>(['zh_cn', 'en_us'])
    const [lang, setLangState] = useState<string>(() => detectLang(['zh_cn', 'en_us']))
    const [pack, setPack] = useState<FlatPack>(BUILTIN['zh_cn'])

    // 初始化: 运行时目录扫描(MC: 每个 .json 一个语种)
    useEffect(() => {
        (async () => {
            let list = ['zh_cn', 'en_us']
            try {
                const remote: any = await api('/ui/api/i18n/list')
                if (Array.isArray(remote) && remote.length) {
                    const set = new Set<string>(['zh_cn', 'en_us'])
                    remote.forEach((m: any) => { if (m && m.lang) set.add(normLang(m.lang)) })
                    list = Array.from(set)
                }
            } catch { }
            setLangs(list)
            setLangState(detectLang(list))
        })()
    }, [])

    // 语言变化: 加载(内置+运行时MC包合并) + html lang/dir
    useEffect(() => {
        let alive = true
            ; (async () => {
                let p: FlatPack = { ...(BUILTIN[normLang(lang)] || {}) }
                try {
                    const remote: any = await api('/ui/api/i18n/' + encodeURIComponent(lang))
                    p = { ...p, ...toFlat(remote) }
                } catch { }
                if (!alive) return
                setPack(p)
                const meta = langMeta(normLang(lang))
                document.documentElement.setAttribute('lang', normLang(lang).replace('_', '-'))
                document.documentElement.setAttribute('dir', meta.rtl ? 'rtl' : 'ltr')
            })()
        return () => { alive = false }
    }, [lang, langs])

    const setLang = useCallback(async (l: string) => {
        const nl = normLang(l)
        try { localStorage.setItem('yatori_lang', nl) } catch { }
        setLangState(nl)
        try { await api('/ui/api/setting', { method: 'POST', body: { i18n: { lang: nl } } }) } catch { }
    }, [])

    const t = useCallback((zhText: string) => {
        const v = pack[zhText]
        return (typeof v === 'string' && v) ? v : zhText
    }, [pack])

    const value = useMemo(() => {
        const meta = langMeta(normLang(lang))
        return {
            lang: normLang(lang),
            langs: langs.map(l => ({ lang: l, ...langMeta(l) })),
            setLang, t,
            fmtDate: (d?: any) => {
                try {
                    return new Intl.DateTimeFormat(normLang(lang).replace('_', '-'),
                        { dateStyle: 'medium', timeStyle: 'medium' }).format(d ? new Date(d) : new Date())
                } catch { return String(d || '') }
            },
            fmtNum: (n: any) => {
                try { return new Intl.NumberFormat(normLang(lang).replace('_', '-')).format(n) }
                catch { return String(n) }
            },
        }
    }, [lang, langs, pack, t, setLang])

    return <I18nCtx.Provider value={value}>{children}</I18nCtx.Provider>
}

const FALLBACK = {
    t: (s: string) => s, lang: 'zh_cn',
    langs: [{ lang: 'zh_cn', nativeName: '简体中文', name: 'Simplified Chinese', rtl: 0 },
    { lang: 'en_us', nativeName: 'English', name: 'English', rtl: 0 }],
    setLang: (_l: string) => { }, fmtDate: (d?: any) => String(d || ''),
    fmtNum: (n: any) => String(n),
}

export function useT() {
    const ctx = useContext(I18nCtx)
    return ctx || FALLBACK
}
