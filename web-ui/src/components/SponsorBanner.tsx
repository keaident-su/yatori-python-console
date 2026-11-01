import React, { useEffect, useState } from 'react';
import { Heart, X } from 'lucide-react';
import { UI } from '../api';
import { useT } from '../i18n';

/* [赞助/赞赏] 图形化界面开屏赞助横幅 + 微信赞赏码展示(会话内可关闭)。
   数据来自 /ui/api/sponsor(开关 sponsor_sw / 自定义文案 / 赞赏码是否存在)。
   赞赏码图片经 /ui/api/sponsor/qr 提供, <img> 无法带 header, 故用 ?token= 鉴权。 */
export default function SponsorBanner() {
    const { t } = useT();
    const [info, setInfo] = useState<any>(null);
    const [show, setShow] = useState(false);
    const [modal, setModal] = useState(false);

    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const d: any = await UI.sponsor();
                if (!alive) return;
                if (d && d.enabled && d.hasQr) {
                    let dismissed = false;
                    try { dismissed = sessionStorage.getItem('yatori_sponsor_dismissed') === '1'; } catch { }
                    setInfo(d);
                    setShow(!dismissed);
                }
            } catch { }
        })();
        return () => { alive = false; };
    }, []);

    if (!info || !show) return null;

    const tk = (() => {
        try { return new URLSearchParams(location.search).get('token') || localStorage.getItem('yui_token') || ''; }
        catch { return ''; }
    })();
    const qr = info.qrUrl
        ? info.qrUrl + (info.qrUrl.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(tk)
        : '';
    const dismiss = () => {
        try { sessionStorage.setItem('yatori_sponsor_dismissed', '1'); } catch { }
        setShow(false);
    };
    const text = (info.text && String(info.text).trim())
        || t('项目完全免费，持续维护需要成本(正版抓包工具/服务器等)。如果它帮到了你，欢迎微信扫码赞赏，支持作者继续维护。');

    return <>
        <div className="ycard mb-4 p-4 flex items-center gap-4" style={{
            borderColor: 'color-mix(in srgb, #f5b301 45%, var(--border))',
            background: 'color-mix(in srgb, #fff6d8 22%, var(--panel-2))'
        }}>
            <div style={{
                width: 44, height: 44, borderRadius: 12, flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'linear-gradient(150deg,#ffd76b,#f0a400)'
            }}>
                <Heart size={22} color="#fff" />
            </div>
            <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold">💖 {t('感谢支持 Yatori 开源刷课系统')}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--subtext)' }}>{text}</div>
            </div>
            {qr && <img src={qr} alt="微信赞赏码" title={t('点击放大')}
                onClick={() => setModal(true)}
                style={{
                    width: 56, height: 56, objectFit: 'contain', borderRadius: 8,
                    background: '#fff', padding: 3, cursor: 'zoom-in', flexShrink: 0
                }} />}
            <button className="ybtn py-1.5 px-3 text-xs" onClick={() => setModal(true)}>
                <Heart size={13} />{t('扫码赞赏')}</button>
            <button className="ybtn py-1.5 px-2 text-xs" title={t('本次不再提示')} onClick={dismiss}>
                <X size={13} /></button>
        </div>

        {modal && <div onClick={() => setModal(false)} style={{
            position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,.55)',
            display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}>
            <div onClick={e => e.stopPropagation()} className="ycard p-5"
                style={{ maxWidth: 360, width: '90%' }}>
                <div className="font-semibold mb-3 text-center">{t('微信扫码赞赏 · 支持作者')}</div>
                {qr && <img src={qr} alt="微信赞赏码"
                    style={{ width: '100%', borderRadius: 12, background: '#fff', padding: 8 }} />}
                <div className="text-xs mt-2 text-center" style={{ color: 'var(--subtext)' }}>
                    {t('感谢您的支持！扫码即可赞赏')}</div>
                <div className="flex justify-center mt-3">
                    <button className="ybtn py-1.5 px-4 text-xs" onClick={() => setModal(false)}>{t('关闭')}</button>
                </div>
            </div>
        </div>}
    </>;
}
