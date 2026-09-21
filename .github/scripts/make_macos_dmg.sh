#!/bin/bash
# ============================================================
# macOS DMG 拖拽安装包生成脚本
# 用法: ./make_macos_dmg.sh <二进制路径> <输出DMG路径> [可选签名身份]
#
# 流程:
#   1. 用 PyInstaller 单文件二进制构造标准 .app bundle
#   2. (可选) codesign 签名 —— 需提供 Apple Developer ID 证书
#   3. hdiutil 创建 DMG(内含 .app + Applications 拖拽链接)
#
# 说明: 未提供签名身份时跳过签名(产物未签名/未公证, 首次打开
#       需右键->打开, 或执行 xattr -cr <app>)
# ============================================================
set -euo pipefail

BIN_PATH="$1"
OUT_DMG="$2"
SIGN_IDENTITY="${3:-}"

if [ ! -f "$BIN_PATH" ]; then
  echo "ERROR: binary not found: $BIN_PATH" >&2
  exit 1
fi

BIN_NAME="$(basename "$BIN_PATH")"
APP_NAME="${BIN_NAME%.exe}"

# ---------- 1. 构造 .app bundle ----------
# 设计: CFBundleExecutable = launcher(双击入口)
#       launcher 通过 `open -a Terminal` 在终端窗口中运行 run-terminal.sh,
#       用户双击 .app 即可看到实时日志(命令行程序不再"静默后台运行")。
#       内核二进制更名为 <APP_NAME>-bin, 由 run-terminal.sh 执行。
#       (不使用 AppleScript/osascript, 避免"自动化控制终端"权限弹窗)
rm -rf "${APP_NAME}.app" dmg_stage
mkdir -p "${APP_NAME}.app/Contents/MacOS"
mkdir -p "${APP_NAME}.app/Contents/Resources"

# 内核二进制(实际程序体)
cp "$BIN_PATH" "${APP_NAME}.app/Contents/MacOS/${APP_NAME}-bin"
chmod +x "${APP_NAME}.app/Contents/MacOS/${APP_NAME}-bin"

# 终端运行脚本(在 Terminal 窗口中运行内核, 实时显示日志)
cat > "${APP_NAME}.app/Contents/MacOS/run-terminal.sh" <<SH
#!/bin/bash
# 在终端窗口中运行主程序(实时日志)。由 .app 双击入口(launcher)调用。
DIR="\$(cd "\$(dirname "\$0")" && pwd)"
cd "\$DIR"
echo "============================================"
echo " Yatori Python Console - 实时日志"
echo " (按 Control+C 或直接关闭本窗口可停止程序)"
echo "============================================"
echo ""
exec "\$DIR/${APP_NAME}-bin"
SH
chmod +x "${APP_NAME}.app/Contents/MacOS/run-terminal.sh"

# 双击入口启动器(Terminal 执行 .sh 不会二次 Gatekeeper 拦截)
cat > "${APP_NAME}.app/Contents/MacOS/launcher" <<'SH'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec open -a Terminal "$DIR/run-terminal.sh"
SH
chmod +x "${APP_NAME}.app/Contents/MacOS/launcher"

cat > "${APP_NAME}.app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.keaident.yatori.python.console</string>
    <key>CFBundleVersion</key>
    <string>1.2.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.2.0</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# ---------- 2. 可选签名 ----------
if [ -n "$SIGN_IDENTITY" ]; then
  echo "==> codesign (identity: $SIGN_IDENTITY)"
  # 先对内部二进制签名, 再对整个 .app 签名(由内到外; launcher/run-terminal.sh 为脚本无需签名)
  codesign --force --options runtime --timestamp \
           --sign "$SIGN_IDENTITY" \
           "${APP_NAME}.app/Contents/MacOS/${APP_NAME}-bin"
  codesign --force --options runtime --timestamp \
           --sign "$SIGN_IDENTITY" \
           "${APP_NAME}.app"
  echo "==> codesign 完成"
else
  echo "==> 未提供签名身份, 跳过 codesign(产物未签名)"
fi

# ---------- 3. 生成 DMG(拖拽安装样式) ----------
mkdir -p dmg_stage
cp -R "${APP_NAME}.app" dmg_stage/
ln -s /Applications dmg_stage/Applications

# 显式计算卷大小: 内容 + 20% + 50MB 余量
# (hdiutil -srcfolder 自动估算对大文件场景不足, 会在写入临时卷时
#  报 'No space left on device')
CONTENT_KB=$(du -sk dmg_stage | awk '{print $1}')
IMG_KB=$(( CONTENT_KB + CONTENT_KB / 5 + 51200 ))
echo "==> 内容 ${CONTENT_KB}KB, 临时卷 ${IMG_KB}KB"

TMP_DMG="/tmp/yatori_dmg_$$.dmg"
MNT_POINT="/tmp/yatori_dmg_mnt_$$"
rm -f "$OUT_DMG" "$TMP_DMG"
mkdir -p "$MNT_POINT"

hdiutil create -size "${IMG_KB}k" -fs HFS+ -volname "$APP_NAME" -ov "$TMP_DMG"
hdiutil attach "$TMP_DMG" -mountpoint "$MNT_POINT"
cp -R dmg_stage/. "$MNT_POINT"/
sync
hdiutil detach "$MNT_POINT"
hdiutil convert "$TMP_DMG" -format UDZO -o "$OUT_DMG"

rm -f "$TMP_DMG"
rm -rf dmg_stage "$MNT_POINT"

echo "==> DMG 生成完成: $OUT_DMG"
