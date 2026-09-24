import type { CanvasDoc, CanvasEdge, CanvasItem, CanvasNodeKind, CanvasSummary, CanvasViewport, Conversation, ConversationSummary, EditMode, Health, ImageRecord, MediaMode, Message, Pads } from './types'

async function parse<T>(res: Promise<Response>): Promise<T> {
  const response = await res
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail || body.error || JSON.stringify(body)
    } catch {
      detail = await response.text()
    }
    throw new Error(typeof detail === 'string' ? detail : '请求失败')
  }
  return response.json() as Promise<T>
}

export function getHealth() {
  return parse<Health>(fetch('/api/health'))
}

export function listConversations(archived = false) {
  return parse<ConversationSummary[]>(fetch(`/api/conversations?archived=${archived}`))
}

export function createConversation(title?: string) {
  return parse<ConversationSummary>(
    fetch('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title || '新对话' }),
    }),
  )
}

export function getConversation(id: string) {
  return parse<Conversation>(fetch(`/api/conversations/${id}`))
}

export function setConversationArchived(id: string, archived: boolean) {
  return parse<ConversationSummary>(
    fetch(`/api/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ archived }),
    }),
  )
}

export function renameConversation(id: string, title: string) {
  return parse<ConversationSummary>(
    fetch(`/api/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  )
}

export function deleteConversation(id: string) {
  return parse<{ ok: boolean; id: string }>(
    fetch(`/api/conversations/${id}`, { method: 'DELETE' }),
  )
}

export function sendMessage(
  id: string,
  payload: {
    prompt: string
    aspect: string
    quality: string
    transparent: boolean
    files: File[]
    mediaMode?: MediaMode
    videoSeconds?: number
    chain?: boolean
    editMode?: EditMode
    sourceImageId?: string
    mask?: Blob | null
    pads?: Pads
  },
) {
  const body = new FormData()
  body.append('prompt', payload.prompt)
  body.append('aspect', payload.aspect)
  body.append('quality', payload.quality)
  body.append('transparent', payload.transparent ? 'true' : 'false')
  body.append('media_mode', payload.mediaMode || 'image')
  if (payload.mediaMode === 'video') {
    body.append('video_seconds', String(payload.videoSeconds ?? 5))
  }
  if (payload.chain === false) body.append('chain', 'false')
  payload.files.forEach((file) => body.append('files', file))
  if (payload.editMode) body.append('edit_mode', payload.editMode)
  if (payload.sourceImageId) body.append('source_image_id', payload.sourceImageId)
  if (payload.mask) body.append('mask', payload.mask, 'mask.png')
  if (payload.pads) {
    body.append('pad_left', String(payload.pads.left))
    body.append('pad_top', String(payload.pads.top))
    body.append('pad_right', String(payload.pads.right))
    body.append('pad_bottom', String(payload.pads.bottom))
  }
  return parse<{ user: Message; assistant: Message }>(
    fetch(`/api/conversations/${id}/messages`, { method: 'POST', body }),
  )
}

export function interrupt(conversationId?: string) {
  return parse<{ status: string }>(
    fetch('/api/interrupt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: conversationId }),
    }),
  )
}

export function listCanvases() {
  return parse<CanvasSummary[]>(fetch('/api/canvases'))
}

export function createCanvas(title?: string) {
  return parse<CanvasDoc>(
    fetch('/api/canvases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title || '未命名画布' }),
    }),
  )
}

export function getCanvas(id: string) {
  return parse<CanvasDoc>(fetch(`/api/canvases/${id}`))
}

export function updateCanvas(id: string, patch: { title?: string; viewport?: CanvasViewport }) {
  return parse<CanvasDoc>(
    fetch(`/api/canvases/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  )
}

export function deleteCanvas(id: string) {
  return parse<{ ok: boolean; id: string }>(fetch(`/api/canvases/${id}`, { method: 'DELETE' }))
}

export function addCanvasItem(
  id: string,
  item: {
    x: number
    y: number
    width: number
    height: number
    image_id?: string | null
    node_kind?: CanvasNodeKind
    title?: string
  },
) {
  return parse<CanvasItem>(
    fetch(`/api/canvases/${id}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    }),
  )
}

export function updateCanvasItem(
  id: string,
  itemId: string,
  patch: {
    x?: number
    y?: number
    width?: number
    height?: number
    z?: number
    image_id?: string
    node_kind?: CanvasNodeKind
    title?: string
  },
) {
  return parse<CanvasItem>(
    fetch(`/api/canvases/${id}/items/${itemId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  )
}

export function deleteCanvasItem(id: string, itemId: string) {
  return parse<{ ok: boolean; id: string }>(
    fetch(`/api/canvases/${id}/items/${itemId}`, { method: 'DELETE' }),
  )
}

export function addCanvasEdge(id: string, edge: { from_item_id: string; to_item_id: string }) {
  return parse<CanvasEdge>(
    fetch(`/api/canvases/${id}/edges`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(edge),
    }),
  )
}

export function deleteCanvasEdge(id: string, edgeId: string) {
  return parse<{ ok: boolean; id: string }>(
    fetch(`/api/canvases/${id}/edges/${edgeId}`, { method: 'DELETE' }),
  )
}

export function uploadCanvasMedia(id: string, file: File) {
  const body = new FormData()
  body.append('file', file)
  return parse<ImageRecord>(fetch(`/api/canvases/${id}/uploads`, { method: 'POST', body }))
}

export function getLibrary() {
  return parse<ImageRecord[]>(fetch('/api/library'))
}

export function imageUrl(id: string) {
  return `/api/images/${id}`
}

export function downloadUrl(id: string) {
  return `/api/images/${id}/download`
}

export function deleteImage(id: string) {
  return parse<{ ok: boolean; id: string }>(
    fetch(`/api/images/${id}`, { method: 'DELETE' }),
  )
}

export function hideImageFromChat(id: string) {
  return parse<{ ok: boolean; id: string }>(
    fetch(`/api/images/${id}/hide`, { method: 'POST' }),
  )
}
