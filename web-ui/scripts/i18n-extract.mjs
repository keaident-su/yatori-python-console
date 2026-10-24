/* 自动化: 中文文案 -> t("...") 包裹 + 导出 zh-CN.json
 * 注入锚定组件函数头(避免插到 helper 里); 支持 function/箭头两种写法。 */
import fs from 'node:fs'
import path from 'node:path'
import { parse } from '@babel/parser'
import _traverse from '@babel/traverse'
import _generate from '@babel/generator'

const traverse = _traverse.default || _traverse
const generate = _generate.default || _generate

const ROOT = path.resolve(import.meta.dirname, '..')
const SRC = path.join(ROOT, 'src')
const OUT_ZH = path.join(SRC, 'locales', 'zh-CN.json')
const CN = /[\u4e00-\u9fa5]/
const SKIP_DIRS = ['node_modules', 'locales', 'components/ui']
const SKIP_FILES = ['api.ts', 'store.ts', 'i18n.tsx', 'main.tsx']

function collectFiles(dir, acc = []) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name)
        const rel = path.relative(SRC, p).replace(/\\/g, '/')
        if (e.isDirectory()) {
            if (SKIP_DIRS.some(d => rel === d || rel.startsWith(d + '/'))) continue
            collectFiles(p, acc)
        } else if (e.name.endsWith('.tsx') || e.name.endsWith('.ts')) {
            if (SKIP_FILES.includes(e.name)) continue
            acc.push(p)
        }
    }
    return acc
}

function relImport(fromFile, targetNoExt) {
    let r = path.relative(path.dirname(fromFile), path.join(SRC, targetNoExt)).replace(/\\/g, '/')
    if (!r.startsWith('.')) r = './' + r
    return r
}

const tCall = (v) => ({
    type: 'CallExpression',
    callee: { type: 'Identifier', name: 't' },
    arguments: [{ type: 'StringLiteral', value: v }],
})

const ANCHORS = [
    /export\s+default\s+function\s+[A-Za-z0-9_]+\s*\([^)]*\)\s*(?::[^{]+)?\{/,
    /(?:const|let)\s+[A-Z][A-Za-z0-9_]*\s*(?::[^=]+)?=\s*\([^)]*\)\s*=>\s*\{/,
    /function\s+[A-Z][A-Za-z0-9_]*\s*\([^)]*\)\s*(?::[^{]+)?\{/,
]

const found = new Set()
let changedFiles = 0

for (const file of collectFiles(SRC)) {
    let code
    try { code = fs.readFileSync(file, 'utf8') } catch { continue }
    if (!CN.test(code)) continue

    let ast
    try {
        ast = parse(code, { sourceType: 'module', plugins: ['jsx', 'typescript'] })
    } catch (e) {
        console.warn('[skip parse]', path.relative(SRC, file), e.message)
        continue
    }

    let needT = false
    const fnStack = []
    const inFunction = () => fnStack.length > 0

    traverse(ast, {
        'FunctionExpression|FunctionDeclaration|ArrowFunctionExpression|ObjectMethod|ClassMethod': {
            enter() { fnStack.push(1) },
            exit() { fnStack.pop() },
        },
        JSXText(p) {
            if (!inFunction()) return
            const raw = p.node.value
            if (!CN.test(raw)) return
            const text = raw.replace(/\s+/g, ' ').trim()
            if (!text) return
            found.add(text)
            needT = true
            p.replaceWith({ type: 'JSXExpressionContainer', expression: tCall(text) })
        },
        StringLiteral(p) {
            if (!inFunction()) return
            const v = p.node.value
            if (!CN.test(v)) return
            if (p.parentPath.isImportDeclaration() || p.parentPath.isExportAllDeclaration()) return
            if (p.parentPath.isCallExpression() && p.parentPath.node.callee &&
                p.parentPath.node.callee.type === 'Identifier' && p.parentPath.node.callee.name === 't') {
                found.add(v)
                return
            }
            if (p.parentPath.isObjectProperty() && p.key === p.node) return
            if (p.parentPath.isJSXAttribute()) {
                found.add(v)
                needT = true
                p.parentPath.node.value = { type: 'JSXExpressionContainer', expression: tCall(v) }
                p.skip()
                return
            }
            found.add(v)
            needT = true
            p.replaceWith(tCall(v))
        },
    })

    if (!needT) continue
    let out = generate(ast, { retainLines: false, jsescOption: { minimal: true } }, code).code

    const imp = `import { useT } from '${relImport(file, 'i18n')}'\n`
    const impRe = /^import[\s\S]*?from\s+['"][^'"]+['"];?\n/gm
    let last = 0, m
    while ((m = impRe.exec(out))) last = m.index + m[0].length
    out = last > 0 ? out.slice(0, last) + imp + out.slice(last) : imp + out

    let injected = false
    for (const re of ANCHORS) {
        const mm = out.match(re)
        if (mm) {
            const idx = out.indexOf(mm[0]) + mm[0].length
            out = out.slice(0, idx) + '\n  const { t } = useT()' + out.slice(idx)
            injected = true
            break
        }
    }
    if (!injected) {
        console.warn('[no-anchor]', path.relative(SRC, file))
        continue
    }

    fs.writeFileSync(file, out, 'utf8')
    changedFiles++
    console.log('[converted]', path.relative(SRC, file))
}

fs.mkdirSync(path.dirname(OUT_ZH), { recursive: true })
const zh = {
    _meta: { name: 'Simplified Chinese', nativeName: '简体中文', rtl: 0 },
    ui: Object.fromEntries([...found].sort().map(k => [k, k])),
    server: {},
}
fs.writeFileSync(OUT_ZH, JSON.stringify(zh, null, 1), 'utf8')
console.log(`[done] files=${changedFiles} keys=${found.size}`)
