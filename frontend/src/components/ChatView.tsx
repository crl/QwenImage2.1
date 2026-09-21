import { Download, Trash2 } from 'lucide-react'
import type { Conversation, ImageRecord, Message } from '../types'
import { downloadUrl, imageUrl } from '../api'

type Props = {
  conversation: Conversation | null
  loading?: boolean
  onOpenImage: (image: ImageRecord) => void
  onDeleteImage: (image: ImageRecord) => void
}

export function ChatView({ conversation, loading, onOpenImage, onDeleteImage }: Props) {
  if (loading && !conversation) {
    return <div className="flex flex-1 items-center justify-center text-sm text-muted">加载对话…</div>
  }
  if (!conversation) return null

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      {conversation.messages.map((message) => (
        <MessageBlock
          key={message.id}
          message={message}
          onOpenImage={onOpenImage}
          onDeleteImage={onDeleteImage}
        />
      ))}
    </div>
  )
}

function DeletedImageFrame({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={`inline-flex self-start items-center justify-center border border-dashed border-border bg-elevated text-sm text-muted ${
        compact ? 'h-8 rounded-xl px-3' : 'h-9 rounded-xl px-3.5'
      }`}
    >
      图片已删除
    </div>
  )
}

function MessageBlock({
  message,
  onOpenImage,
  onDeleteImage,
}: {
  message: Message
  onOpenImage: (image: ImageRecord) => void
  onDeleteImage: (image: ImageRecord) => void
}) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-[22px] bg-panel px-3 py-3 text-[15px] leading-6">
          {message.ref_images.length > 0 && (
            <div className={`flex w-full flex-wrap justify-start gap-2 ${message.content ? 'mb-2' : ''}`}>
              {message.ref_images.map((image) =>
                image.deleted ? (
                  <DeletedImageFrame key={image.id} compact />
                ) : (
                  <button
                    key={image.id}
                    type="button"
                    onClick={() => onOpenImage(image)}
                    className="overflow-hidden rounded-2xl"
                  >
                    <img
                      src={imageUrl(image.id)}
                      alt={image.prompt || '引用图像'}
                      className="h-36 max-w-[220px] object-cover"
                    />
                  </button>
                ),
              )}
            </div>
          )}
          {message.content ? <div className="px-1 whitespace-pre-wrap">{message.content}</div> : null}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {message.status === 'generating' && (
        <div className="overflow-hidden rounded-3xl border border-border bg-panel">
          {message.preview ? (
            <img src={message.preview} alt="生成预览" className="max-h-[70vh] w-full object-contain" />
          ) : (
            <div className="flex h-72 items-center justify-center">
              <div className="h-10 w-10 animate-spin rounded-full border-2 border-muted border-t-fg" />
            </div>
          )}
          <div className="border-t border-border px-4 py-3 text-sm text-muted">
            正在生成
            {message.progress_max > 0 ? ` · ${message.progress}/${message.progress_max}` : '…'}
          </div>
        </div>
      )}
      {message.status === 'error' && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {message.error || '生成失败'}
        </div>
      )}
      {message.images.map((image) =>
        image.deleted ? (
          <DeletedImageFrame key={image.id} />
        ) : (
          <figure key={image.id} className="overflow-hidden rounded-3xl border border-border">
            <button type="button" className="checker block w-full" onClick={() => onOpenImage(image)}>
              <img
                src={imageUrl(image.id)}
                alt={image.prompt || '生成图像'}
                className="max-h-[72vh] w-full object-contain"
              />
            </button>
            <figcaption className="flex items-center justify-between gap-3 border-t border-border bg-elevated px-4 py-3 text-sm text-muted">
              <span>
                {image.width && image.height ? `${image.width}×${image.height}` : 'PNG'}
              </span>
              <span className="flex items-center gap-1">
                <a
                  href={downloadUrl(image.id)}
                  className="inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-fg hover:bg-white/8"
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                  下载
                </a>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-fg hover:bg-white/8"
                  onClick={() => onDeleteImage(image)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  删除
                </button>
              </span>
            </figcaption>
          </figure>
        ),
      )}
    </div>
  )
}
