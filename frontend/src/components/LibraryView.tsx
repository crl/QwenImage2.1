import { Trash2 } from 'lucide-react'
import type { ImageRecord } from '../types'
import { imageUrl } from '../api'

type Props = {
  images: ImageRecord[]
  onOpen: (image: ImageRecord) => void
  onDelete: (image: ImageRecord) => void
}

export function LibraryView({ images, onOpen, onDelete }: Props) {
  if (images.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <h1 className="text-[40px] font-semibold tracking-tight text-fg">创建图像</h1>
        <p className="mt-2 max-w-md text-sm text-muted">用一句话描述画面，也可以上传参考图继续改。</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <h1 className="mb-5 text-2xl font-semibold">图库</h1>
      <div className="columns-2 gap-3 md:columns-3 xl:columns-4">
        {images.map((image) => (
          <div key={image.id} className="group relative mb-3 break-inside-avoid">
            <button
              type="button"
              onClick={() => onOpen(image)}
              className="checker block w-full overflow-hidden rounded-2xl"
            >
              {image.media_type === 'video' ? (
                <video src={imageUrl(image.id)} className="w-full object-cover" muted playsInline preload="metadata" />
              ) : (
                <img src={imageUrl(image.id)} alt={image.prompt || '生成图像'} className="w-full object-cover" />
              )}
            </button>
            <button
              type="button"
              aria-label="删除图片"
              title="删除"
              onClick={(event) => {
                event.stopPropagation()
                onDelete(image)
              }}
              className="absolute top-2 right-2 grid h-8 w-8 place-items-center rounded-full bg-black/70 text-white opacity-90 transition hover:bg-black/85"
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
