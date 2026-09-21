import type { Conversation, ConversationSummary, EditMode, Health, ImageRecord, Message, Pads } from './types'

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
