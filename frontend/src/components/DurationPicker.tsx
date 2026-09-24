import { useEffect, useRef, useState } from 'react'
import { ChevronUp } from 'lucide-react'

const DURATIONS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] as const

type Props = {
  seconds: number
  onSeconds: (value: number) => void
}

export function DurationPicker({ seconds, onSeconds }: Props) {
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

  return (
    <div ref={rootRef} className="relative">
      {open && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-[220px] rounded-2xl border border-border bg-panel p-3 shadow-[0_16px_40px_rgba(0,0,0,0.45)]">
          <p className="mb-2 text-xs text-muted">时长</p>
          <div className="grid grid-cols-4 gap-2">
            {DURATIONS.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => {
                  onSeconds(item)
                  setOpen(false)
                }}
                className={`h-9 rounded-full text-sm transition ${
                  seconds === item ? 'bg-white/16 text-fg ring-1 ring-white/40' : 'bg-white/6 text-muted hover:bg-white/10 hover:text-fg'
                }`}
              >
                {item}s
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
        aria-label="视频时长"
        onClick={() => setOpen((value) => !value)}
      >
        <span>{seconds}秒</span>
        <ChevronUp className={`h-3.5 w-3.5 transition ${open ? '' : 'rotate-180'}`} aria-hidden="true" />
      </button>
    </div>
  )
}
