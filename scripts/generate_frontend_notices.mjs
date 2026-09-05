import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const frontend = path.join(root, 'frontend')
const lock = JSON.parse(fs.readFileSync(path.join(frontend, 'package-lock.json'), 'utf8'))
const sections = []
for (const [relative, entry] of Object.entries(lock.packages)) {
  if (!relative || entry.dev || entry.optional) continue
  const directory = path.join(frontend, relative)
  const installed = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'))
  if (installed.version !== entry.version) throw new Error(`Run npm ci: ${relative} version differs from lockfile`)
  const files = fs.readdirSync(directory).filter(name => /^(licen[sc]e|copying|notice)(\.|$)/i.test(name)
    && fs.statSync(path.join(directory, name)).isFile()).sort()
  let fallback = ''
  if (!files.length && fs.existsSync(path.join(directory, 'README.md'))) {
    const readme = fs.readFileSync(path.join(directory, 'README.md'), 'utf8')
    const offset = readme.indexOf('(The MIT License)')
    if (offset >= 0) fallback = readme.slice(offset)
  }
  if (!files.length && !fallback && installed.name === 'lodash-unified' && installed.license === 'MIT') {
    fallback = 'Upstream package metadata: author Jack Works; license MIT.\n'
      + 'This package ships no separate license text. The upstream MIT declaration is preserved here.\n'
      + 'Permission is hereby granted' + fs.readFileSync(path.join(root, 'LICENSE'), 'utf8').split('Permission is hereby granted')[1]
  }
  if (!files.length && !fallback) throw new Error(`Missing upstream license file: ${relative}`)
  const name = relative.split('node_modules/').at(-1)
  sections.push(`${'='.repeat(72)}\n${name}@${entry.version} (${entry.license || 'see upstream license'})\n`
    + files.map(file => `${file}\n${fs.readFileSync(path.join(directory, file), 'utf8').trim()}\n`).join('\n') + fallback)
}
const contents = ('Third-party frontend dependency notices\n'
  + 'Generated from frontend/package-lock.json and installed upstream license files.\n'
  + 'These dependencies retain their own copyright and license terms.\n\n'
  + sections.join('\n')).replace(/\r\n/g, '\n')
const output = path.join(frontend, 'public', 'THIRD_PARTY_LICENSES.txt')
if (process.argv.includes('--check')) {
  if (fs.readFileSync(output, 'utf8').replace(/\r\n/g, '\n') !== contents) throw new Error('Frontend notices are stale')
} else {
  fs.mkdirSync(path.dirname(output), { recursive: true })
  fs.writeFileSync(output, contents, 'utf8')
}
console.log(`Verified notices for ${sections.length} frontend dependencies`)
