export type Health = {
  ok: boolean
  error?: string
  comfyui_version?: string
  pytorch?: string
  devices?: { name?: string; vram_total?: number; vram_free?: number }[]
}

export type ImageRecord = {
  id: string
  conversation_id: string
  message_id: string | null
  filename: string
  prompt: string | null
  width: number | null
  height: number | null
  created_at: string
  url: string
  deleted?: boolean
}

export type Message = {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  image_ids: string[]
  ref_image_ids: string[]
  params: {
    aspect?: string
    quality?: string
    transparent?: boolean
    steps?: number
    mode?: string
  }
  status: 'generating' | 'done' | 'error' | null
  progress: number
  progress_max: number
  preview: string | null
  error: string | null
  created_at: string
  images: ImageRecord[]
  ref_images: ImageRecord[]
}

export type ConversationSummary = {
  id: string
  title: string
  created_at: string
  updated_at: string
  archived?: boolean
}

export type Conversation = ConversationSummary & {
  messages: Message[]
}

export type StudioEvent =
  | { type: 'snapshot'; conversation: Conversation }
  | { type: 'progress'; message_id: string; value: number; max: number }
  | { type: 'preview'; message_id: string; data_url: string }
  | { type: 'done'; message: Message; images: ImageRecord[] }
  | { type: 'error'; message_id: string; error: string; message?: Message }

export const ASPECTS = ['auto', '1:1', '9:16', '16:9', '3:4', '4:3', '3:2', '2:3', '4:5', '5:4', '21:9'] as const
export type Aspect = (typeof ASPECTS)[number]
export type Quality = '1k' | '2k' | '4k'
export type EditMode = 'erase' | 'outpaint' | 'enhance'
export type Pads = {
  left: number
  top: number
  right: number
  bottom: number
}
