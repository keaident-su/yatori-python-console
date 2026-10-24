/* 审计: 查找 t(...) 调用不在 "const { t } = useT()" 作用域内的位置(运行时会崩) */
import fs from 'node:fs'
import path from 'node:path'
import { parse } from '@babel/parser'
import _traverse from '@babel/traverse'

const traverse = _traverse.default || _traverse
const SRC = path.resolve(import.meta.dirname, '..', 'src')

function collect(dir, acc = []) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name)
        const rel = path.relative(SRC, p).replace(/\\/g, '/')
        if (e.isDirectory()) { if (rel.startsWith('node_modules') || rel.startsWith('locales')) continue; collect(p, acc) }
        else if (e.name.endsWith('.tsx') || e.name.endsWith('.ts')) acc.push(p)
    }
    return acc
}

let problems = 0
for (const file of collect(SRC)) {
    let code
    try { code = fs.readFileSync(file, 'utf8') } catch { continue }
    if (!/\bt\(/.test(code)) continue
    let ast
    try { ast = parse(code, { sourceType: 'module', plugins: ['jsx', 'typescript'] }) } catch { continue }
    // 收集所有声明了 t 的函数作用域(通过 useT 解构)
    traverse(ast, {
        CallExpression(p) {
            const c = p.node.callee
            if (!(c.type === 'Identifier' && c.name === 't')) return
            // 向上找函数作用域, 看其中是否有 `const/let/var {..t..} = useT()`
            let fn = p.getFunctionParent()
            let ok = false
            while (fn) {
                const body = fn.node.body
                if (body && body.type === 'BlockStatement') {
                    for (const st of body.body) {
                        if (st.type === 'VariableDeclaration' && st.declarations) {
                            for (const d of st.declarations) {
                                if (d.id && d.id.type === 'ObjectPattern') {
                                    const names = d.id.properties.map(x => x.key && x.key.name).filter(Boolean)
                                    const ini = d.init
                                    if (names.includes('t') && ini && ini.type === 'CallExpression'
                                        && ini.callee && ini.callee.name === 'useT') { ok = true }
                                }
                            }
                        }
                    }
                }
                if (ok) break
                fn = fn.getFunctionParent()
            }
            if (!ok) {
                problems++
                const line = p.node.loc ? p.node.loc.start.line : '?'
                console.log(`[UNSAFE] ${path.relative(SRC, file)}:${line}  t(${JSON.stringify(p.node.arguments[0] && (p.node.arguments[0].value || '?'))})`)
            }
        },
    })
}
console.log(`[audit] unsafe=${problems}`)
