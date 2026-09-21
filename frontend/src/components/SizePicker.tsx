import { useEffect, useRef, useState } from 'react'
import { ChevronUp } from 'lucide-react'
import { ASPECTS, type Aspect, type Quality } from '../types'

const QUALITIES: { id: Quality; label: string }[] = [
  { id: '1k', label: '1K' },
  { id: '2k', label: '2K' },
  { id: '4k', label: '4K' },
]

type Props = {
  aspect: Aspect
  quality: Quality
  onAspect: (value: Aspect) => void
  onQuality: (value: Quality) => void
}

export function SizePicker({ aspect, quality, onAspect, onQuality }: Props) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointer(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('pointerdown', onPointer)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onPointer)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const qualityLabel = QUALITIES.find((item) => item.id === quality)?.label ?? '1K'
  const aspectLabel = aspect === 'auto' ? '自适应' : aspect

  return (
    <div ref={rootRef} className="relative">
      {open && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-[340px] rounded-2xl border border-border bg-panel p-3 shadow-[0_16px_40px_rgba(0,0,0,0.45)]">
          <p className="mb-2 text-xs text-muted">分辨率</p>
          <div className="mb-3 grid grid-cols-3 gap-2">
            {QUALITIES.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onQuality(item.id)}
                className={`h-9 rounded-full text-sm transition ${
                  quality === item.id ? 'bg-white/16 text-fg ring-1 ring-white/40' : 'bg-white/6 text-muted hover:bg-white/10 hover:text-fg'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <p className="mb-2 text-xs text-muted">比例</p>
          <div className="grid grid-cols-5 gap-2">
            {ASPECTS.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => onAspect(item)}
                className={`flex h-[72px] flex-col items-center justify-center gap-1.5 rounded-xl text-[11px] transition ${
                  aspect === item ? 'bg-white/12 text-fg ring-1 ring-white/45' : 'text-muted hover:bg-white/8 hover:text-fg'
                }`}
              >
                <AspectGlyph ratio={item} />
                <span>{item === 'auto' ? '自适应' : item}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <button
        type="button"
        className="inline-flex h-9 items-center gap-1.5 rounded-full px-2.5 text-xs text-muted transition hover:bg-white/8 hover:text-fg"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="分辨率与比例"
        onClick={() => setOpen((value) => !value)}
      >
        <AspectGlyph ratio={aspect} />
        <span>
          {aspectLabel} · {qualityLabel}
        </span>
        <ChevronUp className={`h-3.5 w-3.5 transition ${open ? '' : 'rotate-180'}`} aria-hidden="true" />
      </button>
    </div>
  )
}

function AspectGlyph({ ratio }: { ratio: string }) {
  const [w, h] = ratio === 'auto' ? [14, 14] : ratio.split(':').map(Number)
  const max = Math.max(w, h) || 1
  const width = Math.max(8, (14 * w) / max)
  const height = Math.max(8, (14 * h) / max)
  return (
    <span
      className="rounded-[3px] border border-current opacity-80"
      style={{ width, height }}
      aria-hidden="true"
    />
  )
}
