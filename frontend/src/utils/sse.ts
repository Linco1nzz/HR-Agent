/** 浏览器端 SSE 读取：把 ReadableStream 解析成 { event, data } 帧。 */

export interface SseFrame {
  event: string
  data: string
}

function parseFrame(raw: string): SseFrame | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    if (colon === -1) continue
    const field = line.slice(0, colon)
    const value = line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') {
      event = value
    } else if (field === 'data') {
      dataLines.push(value)
    }
  }

  if (!dataLines.length) return null
  return { event, data: dataLines.join('\n') }
}

/**
 * 逐帧读取 SSE。支持 CRLF、注释行（如 `: keep-alive`）与跨 chunk 截断的帧。
 * 回调抛出的异常会中断读取并向上传递。
 */
export async function consumeSse(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: SseFrame) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const flush = (): void => {
    if (!buffer.trim()) {
      buffer = ''
      return
    }
    const frame = parseFrame(buffer)
    buffer = ''
    if (frame) onFrame(frame)
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = buffer.replace(/\r\n/g, '\n')

      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const raw = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const frame = parseFrame(raw)
        if (frame) onFrame(frame)
        boundary = buffer.indexOf('\n\n')
      }
    }

    buffer += decoder.decode()
    buffer = buffer.replace(/\r\n/g, '\n')
    flush()
  } finally {
    reader.releaseLock()
  }
}
