import { useEffect } from 'react'
import { Download, MessageSquare, Trash2, X } from 'lucide-react'
import type { ImageRecord } from '../types'
import { downloadUrl, imageUrl } from '../api'

type Props = {
  image: ImageRecord | null
  onClose: () => void
  onOpenChat: (conversationId: string) => void
  onDelete: (image: ImageRecord) => void
}

export function Lightbox({ image, onClose, onOpenChat, onDelete }: Props) {
  useEffect(() => {
    if (!image) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [image, onClose])

  if (!image) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" role="dialog" aria-modal="true">
      <button type="button" className="absolute inset-0 cursor-default" aria-label="关闭预览" onClick={onClose} />
      <div className="relative z-10 flex max-h-full max-w-5xl flex-col gap-3">
        <div className="flex justify-end gap-2">
          <a
            href={downloadUrl(image.id)}
            className="grid h-10 w-10 place-items-center rounded-full bg-white/10 text-fg hover:bg-white/20"
            aria-label="下载"
          >
            <Download className="h-5 w-5" aria-hidden="true" />
          </a>
          <button
            type="button"
            className="grid h-10 w-10 place-items-center rounded-full bg-white/10 text-fg hover:bg-white/20"
            aria-label="在对话中编辑"
            onClick={() => onOpenChat(image.conversation_id)}
          >
            <MessageSquare className="h-5 w-5" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="grid h-10 w-10 place-items-center rounded-full bg-white/10 text-fg hover:bg-white/20"
            aria-label="删除图片"
            onClick={() => onDelete(image)}
          >
            <Trash2 className="h-5 w-5" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="grid h-10 w-10 place-items-center rounded-full bg-white/10 text-fg hover:bg-white/20"
            aria-label="关闭"
            onClick={onClose}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="checker max-h-[80vh] overflow-hidden rounded-3xl">
          <img src={imageUrl(image.id)} alt={image.prompt || '生成图像'} className="max-h-[80vh] w-full object-contain" />
        </div>
        {image.prompt && <p className="max-w-3xl text-sm text-muted">{image.prompt}</p>}
      </div>
    </div>
  )
}
