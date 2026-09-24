import { useEffect, useState } from 'react'
import { Download, Pencil, Trash2, X } from 'lucide-react'
import type { ImageRecord } from '../types'
import { downloadUrl, imageUrl } from '../api'

type Props = {
  image: ImageRecord | null
  onClose: () => void
  onEdit: (image: ImageRecord) => void
  onDelete: (image: ImageRecord) => void
}

export function Lightbox({ image, onClose, onEdit, onDelete }: Props) {
  const [actual, setActual] = useState(false)
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null)
  const isVideo = image?.media_type === 'video'

  useEffect(() => {
    setActual(false)
    setNatural(null)
  }, [image?.id])

  useEffect(() => {
    if (!image) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [image, onClose])

  if (!image) return null

  const pixelWidth = image.width || natural?.width
  const pixelHeight = image.height || natural?.height

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" role="dialog" aria-modal="true">
      <button type="button" className="absolute inset-0 cursor-default" aria-label="关闭预览" onClick={onClose} />
      <div
        className={`relative z-10 flex max-h-full flex-col gap-3 ${actual && !isVideo ? 'w-fit max-w-[calc(100vw-3rem)]' : 'max-w-5xl'}`}
      >
        <div className="flex justify-end gap-2">
          {!isVideo && (
            <button
              type="button"
              className={`grid h-10 min-w-10 place-items-center rounded-full px-2 text-xs font-medium ${actual ? 'bg-white/25 text-fg' : 'bg-white/10 text-fg hover:bg-white/20'}`}
              aria-label={actual ? '适应窗口' : '1:1 显示'}
              aria-pressed={actual}
              onClick={() => setActual((value) => !value)}
            >
              1:1
            </button>
          )}
          <a
            href={downloadUrl(image.id)}
            className="grid h-10 w-10 place-items-center rounded-full bg-white/10 text-fg hover:bg-white/20"
            aria-label="下载"
          >
            <Download className="h-5 w-5" aria-hidden="true" />
          </a>
          {!isVideo && (
            <button
              type="button"
              className="grid h-10 w-10 place-items-center rounded-full bg-white/10 text-fg hover:bg-white/20"
              aria-label="编辑这张图"
              onClick={() => onEdit(image)}
            >
              <Pencil className="h-5 w-5" aria-hidden="true" />
            </button>
          )}
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
        <div className={`checker overflow-auto rounded-3xl ${actual && !isVideo ? 'max-h-[calc(100vh-8rem)] max-w-full' : 'max-h-[80vh] overflow-hidden'}`}>
          {isVideo ? (
            <video
              src={imageUrl(image.id)}
              controls
              autoPlay
              playsInline
              className="max-h-[80vh] w-full bg-black object-contain"
            />
          ) : (
            <img
              src={imageUrl(image.id)}
              alt={image.prompt || '生成图像'}
              className={actual ? 'max-h-none max-w-none' : 'max-h-[80vh] w-full object-contain'}
              style={actual && pixelWidth && pixelHeight ? { width: pixelWidth, height: pixelHeight } : undefined}
              onLoad={(event) => {
                const img = event.currentTarget
                setNatural({ width: img.naturalWidth, height: img.naturalHeight })
              }}
            />
          )}
        </div>
        {image.prompt && <p className="max-w-3xl text-sm text-muted">{image.prompt}</p>}
      </div>
    </div>
  )
}
