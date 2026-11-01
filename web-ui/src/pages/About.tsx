import React, { useEffect, useState } from 'react';
import { Info, Megaphone } from 'lucide-react';
import { UI } from '../api';
import { useUI } from '../store';
import { useT } from '../i18n'
export default function About() {
  const { t } = useT()
  const {
    showToast
  } = useUI();
  const [d, setD] = useState<any>({});
  useEffect(() => {
    UI.about().then(setD).catch((e: any) => showToast(e.message, 'err'));
  }, []);
  return <div>
            <h1 className="text-xl font-bold mb-5">{t("关于本项目")}</h1>
            <div className="ycard p-6 mb-4">
                <div className="flex items-center gap-3 mb-3">
                    <Info size={18} style={{
          color: 'var(--primary)'
        }} />
                    <span className="font-semibold">{t("Yatori 刷课系统 · 桌面版")}</span>
                </div>
                <div className="text-sm space-y-1" style={{
        color: 'var(--subtext)'
      }}>
                    <div>{t("版本: v")}{d.version || '...'}</div>
                    <div>{t("图形界面: React + pywebview 桌面窗口(2026-10-23 新增, 支持主题切换/自定义背景)")}</div>
                    <div>{t("服务端: Python FastAPI 本地服务(仅127.0.0.1 + 随机令牌鉴权)")}</div>
                    <div>{t("配置互通: 与 WordPress 插件版共用同一 config.yaml 与数据库, 两版可并存")}</div>
                    <div className="pt-2">{t("免责声明: 本程序仅供个人已授权账号的学习任务管理, 请遵守平台规则。")}</div>
                </div>
            </div>
            <div className="ycard p-6">
                <div className="flex items-center gap-3 mb-3">
                    <Megaphone size={18} style={{
          color: 'var(--warn)'
        }} />
                    <span className="font-semibold">{t("公告")}</span>
                </div>
                <div className="text-sm whitespace-pre-wrap" style={{
        color: 'var(--subtext)'
      }}>
                    {d.announcement || t("暂无公告")}
                </div>
            </div>
        </div>;
}