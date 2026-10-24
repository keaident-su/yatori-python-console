import React, { useEffect, useRef, useState } from 'react';
import { Save, Image as ImageIcon, Palette, RefreshCw, X } from 'lucide-react';
import { UI } from '../api';
import { useUI, applyRandomBgApi } from '../store';
import { useT } from '../i18n'
export default function SettingsPage() {
  const { t, lang, langs, setLang } = useT()
  const {
    showToast,
    theme,
    setTheme,
    bgUrl,
    setBgUrl,
    bgMode,
    setBgMode,
    bgApi,
    setBgApi
  } = useUI();
  const [bs, setBs] = useState<any>({});
  const [ai, setAi] = useState<any>({});
  const [em, setEm] = useState<any>({});
  const [sd, setSd] = useState<any>({});
  const [loading, setLoading] = useState(false);
  const [bgInput, setBgInput] = useState(bgUrl);
  const fileRef = useRef<HTMLInputElement>(null);
  const load = async () => {
    setLoading(true);
    try {
      const d: any = await UI.getSetting();
      setBs(d.basicSetting || {});
      setAi(d.aiSetting || {});
      setEm(d.emailInform || {});
      setSd(d.showdocInform || {});
    } catch (e: any) {
      showToast(e.message, 'err');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, []);
  const save = async () => {
    try {
      await UI.saveSetting({
        basicSetting: bs,
        aiSetting: ai,
        emailInform: em,
        showdocInform: sd
      });
      showToast(t("配置已保存并热重载"));
    } catch (e: any) {
      showToast(e.message, 'err');
    }
  };
  const uploadBg = async (f: File) => {
    if (f.size > 8 * 1024 * 1024) return showToast(t("图片需小于8MB"), 'err');
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const r: any = await UI.uploadBg(String(reader.result));
        const path = r.path;
        // 带上 token 让 <img> 可直接加载
        const tk = new URLSearchParams(location.search).get('token') || localStorage.getItem('yui_token') || '';
        setBgUrl(path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(tk));
        setBgInput('');
        showToast(t("背景图已更新"));
      } catch (e: any) {
        showToast(e.message, 'err');
      }
    };
    reader.readAsDataURL(f);
  };
  const Row = ({
    label,
    children,
    hint
  }: any) => <div className="flex items-center justify-between py-2.5 border-b" style={{
    borderColor: 'var(--border)'
  }}>
            <div>
                <div className="text-sm">{label}</div>
                {hint && <div className="text-xs mt-0.5" style={{
        color: 'var(--subtext)'
      }}>{hint}</div>}
            </div>
            <div className="w-72">{children}</div>
        </div>;
  const Num = ({
    v,
    set,
    ...p
  }: any) => <input className="yinput" type="number" value={v ?? 0} onChange={e => set(+e.target.value)} {...p} />;
  return <div>
            <div className="flex items-center justify-between mb-5">
                <h1 className="text-xl font-bold">{t("全局设置")}</h1>
                <div className="flex gap-2">
                    <button className="ybtn" onClick={load} disabled={loading}>
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{t("重载")}</button>
                    <button className="ybtn ybtn-primary" onClick={save}>
                        <Save size={14} />{t("保存配置")}</button>
                </div>
            </div>

            {/* [V3.0.11] 界面语言: 运行时语言包(assets/i18n/*.json)，丢文件即支持新语种 */}
            <div className="ycard p-3 mb-4 flex items-center gap-3 flex-wrap">
                <span className="text-sm font-medium">{t("语言")}</span>
                <select className="yselect w-56" value={lang} onChange={e => setLang(e.target.value)}>
                    {langs.map((x: any) => (
                        <option key={x.lang} value={x.lang}>
                            {x.nativeName || x.name || x.lang}
                        </option>
                    ))}
                </select>
                <span className="text-xs" style={{ color: 'var(--subtext)' }}>
                    assets/i18n/*.json — {t("保存并实时生效")}
                </span>
            </div>

            {/* 界面外观 */}
            <div className="ycard p-5 mb-4">
                <div className="flex items-center gap-2 mb-3">
                    <Palette size={16} style={{
          color: 'var(--primary)'
        }} />
                    <span className="font-semibold">{t("界面外观")}</span>
                </div>
                <Row label={t("主题风格")}>
                    <select className="yselect" value={theme} onChange={e => setTheme(e.target.value as any)}>
                        <option value="blue">{t("蓝白简洁(默认)")}</option>
                        <option value="dark">{t("暗色霓虹")}</option>
                        <option value="frost">{t("磨砂灰白黑")}</option>
                    </select>
                </Row>
                {/* ===== 背景设置(2026-10-24三来源: 本地上传WebP / 固定URL / 随机图片API) ===== */}
                <div className="py-3 border-b" style={{
        borderColor: 'var(--border)'
      }}>
                    <div className="flex items-center justify-between mb-2">
                        <div>
                            <div className="text-sm">{t("背景图片来源")}</div>
                            <div className="text-xs mt-0.5" style={{
              color: 'var(--subtext)'
            }}>{t("本地上传支持 PNG/JPG/WebP(自动压缩) · 随机图片API每次启动自动换图")}</div>
                        </div>
                        <button className="ybtn py-1.5 px-3 text-xs" onClick={() => {
            setBgUrl('');
            setBgMode('');
            setBgInput('');
          }}>
                            <X size={13} />{t("清除背景")}</button>
                    </div>
                    <div className="flex gap-2 mb-3">
                        {([['upload', t("本地上传")], ['url', t("固定图片URL")], ['api', t("随机图片API")]] as const).map(([m, label]) => <button key={m} className={'ybtn py-1.5 px-3 text-xs'} style={{
            background: bgMode === m ? 'var(--primary)' : 'var(--panel-2)',
            color: bgMode === m ? '#fff' : 'var(--text)',
            borderColor: bgMode === m ? 'var(--primary)' : 'var(--border)',
            fontWeight: bgMode === m ? 600 : 400
          }} onClick={() => setBgMode(m)}>{label}</button>)}
                    </div>
                    {bgMode === 'upload' && <div className="flex gap-2 items-center">
                            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/bmp" className="hidden" onChange={e => e.target.files?.[0] && uploadBg(e.target.files[0])} />
                            <button className="ybtn py-1.5 px-3 text-xs" onClick={() => fileRef.current?.click()}>
                                <ImageIcon size={13} />{t("选择图片(支持 WebP)")}</button>
                            <span className="text-xs" style={{
            color: 'var(--subtext)'
          }}>{t("上传后自动转 WebP 并限制宽度1920(加载更快)")}</span>
                        </div>}
                    {bgMode === 'url' && <div className="flex gap-2">
                            <input className="yinput flex-1" placeholder={t("https://...图片地址")} value={bgInput} onChange={e => setBgInput(e.target.value)} />
                            <button className="ybtn py-1.5 px-3 text-xs" onClick={() => {
            if (bgInput.trim()) {
              setBgUrl(bgInput.trim());
              showToast(t("背景已应用"));
            }
          }}>{t("应用")}</button>
                        </div>}
                    {bgMode === 'api' && <div>
                            <div className="flex gap-2">
                                <input className="yinput flex-1" placeholder={t("随机图片API地址, 如 https://api.example.com/random")} value={bgApi} onChange={e => setBgApi(e.target.value)} />
                                <button className="ybtn py-1.5 px-3 text-xs" onClick={() => {
              if (bgApi.trim()) {
                applyRandomBgApi(bgApi.trim());
                showToast(t("已从API换一张背景"));
              }
            }}>{t("应用并换一张")}</button>
                            </div>
                            <div className="text-xs mt-1.5" style={{
            color: 'var(--subtext)'
          }}>{t("每次程序启动时会自动从该地址拉取新图(自动附加随机参数防缓存)")}</div>
                        </div>}
                </div>
            </div>

            {/* 基础设置 */}
            <div className="ycard p-5 mb-4">
                <div className="font-semibold mb-3">{t("基础设置")}</div>
                <Row label={t("学习次数智能封顶")} hint={t("开启=每门课最多30次(平台满分线,省时); 关闭=按账号设定次数跑满")}>
                    <select className="yselect" value={bs.studyCountCap ?? 1} onChange={e => setBs({
          ...bs,
          studyCountCap: +e.target.value
        })}>
                        <option value={1}>{t("开启(封顶30)")}</option>
                        <option value={0}>{t("关闭(按设定跑满)")}</option>
                    </select>
                </Row>
                <Row label={t("大众云学基地址")} hint={t("仅大众云学平台使用,留空用内置默认")}>
                    <input className="yinput" value={bs.dzyxBaseUrl || ''} onChange={e => setBs({
          ...bs,
          dzyxBaseUrl: e.target.value
        })} />
                </Row>
                <Row label={t("图片题OCR识别")}>
                    <select className="yselect" value={bs.ocrImageQuestion ?? 1} onChange={e => setBs({
          ...bs,
          ocrImageQuestion: +e.target.value
        })}>
                        <option value={1}>{t("开启")}</option><option value={0}>{t("关闭")}</option>
                    </select>
                </Row>
                <Row label={t("全核模式 fullCpuMode")}>
                    <select className="yselect" value={bs.fullCpuMode ?? 0} onChange={e => setBs({
          ...bs,
          fullCpuMode: +e.target.value
        })}>
                        <option value={0}>{t("默认")}</option><option value={1}>{t("全核(高并发)")}</option>
                    </select>
                </Row>
                <Row label={t("完成提示音")}>
                    <select className="yselect" value={bs.completionTone ?? 1} onChange={e => setBs({
          ...bs,
          completionTone: +e.target.value
        })}>
                        <option value={1}>{t("开启")}</option><option value={0}>{t("关闭")}</option>
                    </select>
                </Row>
            </div>

            {/* AI 设置 */}
            <div className="ycard p-5 mb-4">
                <div className="font-semibold mb-3">{t("AI 大模型自动答题")}</div>
                <Row label={t("AI 类型")}>
                    <select className="yselect" value={ai.aiType || 'DEEPSEEK'} onChange={e => setAi({
          ...ai,
          aiType: e.target.value
        })}>
                        {['DEEPSEEK', 'TONGYI', 'CHATGLM', 'XINGHUO', 'DOUBAO', 'OPENAI', 'SILICON', 'METAAI', 'OTHER'].map(v => <option key={t} value={t}>{t}</option>)}
                    </select>
                </Row>
                <Row label={t("模型名称")}>
                    <input className="yinput" value={ai.model || ''} onChange={e => setAi({
          ...ai,
          model: e.target.value
        })} placeholder={t("如 deepseek-chat")} />
                </Row>
                <Row label="API Key">
                    <input className="yinput" type="password" value={ai.API_KEY || ai.apiKey || ''} onChange={e => setAi({
          ...ai,
          API_KEY: e.target.value
        })} />
                </Row>
                <Row label={t("自定义 API 地址")}>
                    <input className="yinput" value={ai.aiUrl || ai.url || ''} onChange={e => setAi({
          ...ai,
          aiUrl: e.target.value
        })} />
                </Row>
            </div>

            {/* 推送通知 */}
            <div className="ycard p-5 mb-4">
                <div className="font-semibold mb-3">{t("推送通知(邮件/ShowDoc)")}</div>
                <Row label={t("邮件通知")}>
                    <select className="yselect" value={em.sw ?? 0} onChange={e => setEm({
          ...em,
          sw: +e.target.value
        })}>
                        <option value={0}>{t("关闭")}</option><option value={1}>{t("开启")}</option>
                    </select>
                </Row>
                <Row label={t("SMTP 服务器")}>
                    <input className="yinput" value={em.SMTPHost || ''} onChange={e => setEm({
          ...em,
          SMTPHost: e.target.value
        })} placeholder="smtp.xx.com" />
                </Row>
                <Row label={t("SMTP 端口 / 账号 / 密码")}>
                    <div className="flex gap-1">
                        <input className="yinput w-20" type="number" value={em.SMTPPort || 465} onChange={e => setEm({
            ...em,
            SMTPPort: +e.target.value
          })} />
                        <input className="yinput flex-1" value={em.userName || ''} onChange={e => setEm({
            ...em,
            userName: e.target.value
          })} placeholder={t("邮箱")} />
                        <input className="yinput flex-1" type="password" value={em.password || ''} onChange={e => setEm({
            ...em,
            password: e.target.value
          })} placeholder={t("密码")} />
                    </div>
                </Row>
                <Row label={t("ShowDoc 推送")}>
                    <select className="yselect" value={sd.sw ?? 0} onChange={e => setSd({
          ...sd,
          sw: +e.target.value
        })}>
                        <option value={0}>{t("关闭")}</option><option value={1}>{t("开启")}</option>
                    </select>
                </Row>
                <Row label="ShowDoc URL">
                    <input className="yinput" value={sd.url || ''} onChange={e => setSd({
          ...sd,
          url: e.target.value
        })} />
                </Row>
            </div>

            <div className="flex justify-end">
                <button className="ybtn ybtn-primary" onClick={save}>
                    <Save size={14} />{t("保存配置")}</button>
            </div>
        </div>;
}