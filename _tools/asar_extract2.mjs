// 从 app.asar 抽取指定文件（只读）。用法：node asar_extract2.mjs <asar内路径> [输出路径]
import { openSync, readSync, closeSync, writeFileSync } from 'node:fs'

const asar = 'C:\\Users\\Administrator\\AppData\\Local\\Programs\\DeepSeek Harness\\resources\\app.asar'
const target = process.argv[2]
const outPath = process.argv[3]

const fd = openSync(asar, 'r')
try {
  const head = Buffer.alloc(16)
  readSync(fd, head, 0, 16, 0)
  const pickleSize = head.readUInt32LE(4)
  const jsonSize = head.readUInt32LE(8)
  const jsonBuf = Buffer.alloc(jsonSize)
  readSync(fd, jsonBuf, 0, jsonSize, 12)
  const header = JSON.parse(jsonBuf.toString('utf8'))
  const baseOffset = 8 + pickleSize

  const parts = target.split('/').filter(Boolean)
  let node = header
  for (let i = 0; i < parts.length; i++) {
    const next = node.files && node.files[parts[i]]
    if (!next) {
      console.error('NOT FOUND at segment: ' + parts[i])
      process.exit(2)
    }
    node = next
  }
  if (node.files) {
    console.error('IS A DIRECTORY')
    process.exit(3)
  }
  const start = baseOffset + Number(node.offset)
  const size = Number(node.size)
  const body = Buffer.alloc(size)
  readSync(fd, body, 0, size, start)
  if (outPath) {
    writeFileSync(outPath, body)
    console.error(`WROTE ${outPath} (${body.length} B)`)
  } else {
    process.stdout.write(body)
  }
} finally {
  closeSync(fd)
}
