import { useCallback, useEffect, useImperativeHandle, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from 'react'
import { Eraser, Expand, Minus, Plus, Sparkles, Undo2, X } from 'lucide-react'
import type { EditMode, ImageRecord, Pads } from '../types'
import { imageUrl } from '../api'

export type ImageEditorHandle = {
  exportMask: () => Promise<Blob | null>
  pads: Pads
  hasMask: boolean
}

type Props = {
  image: ImageRecord
  tool: EditMode
  busy?: boolean
  onTool: (tool: EditMode) => void
  onClose: () => void
  onEnhance: () => void
  onMaskChange: (hasMask: boolean) => void
  onPadsChange: (pads: Pads) => void
  editorRef: RefObject<ImageEditorHandle | null>
}

const EMPTY_PADS: Pads = { left: 0, top: 0, right: 0, bottom: 0 }
const PAD_STEP = 128
const MAX_PAD = 1024

export function ImageEditor({
  image,
  tool,
  busy,
  onTool,
  onClose,
  onEnhance,
  onMaskChange,
  onPadsChange,
  editorRef,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const lastRef = useRef<{ x: number; y: number } | null>(null)
  const drawingRef = useRef(false)
  const historyRef = useRef<ImageData[]>([])
  const [brush, setBrush] = useState(48)
  const [hasMask, setHasMask] = useState(false)
  const [pads, setPads] = useState<Pads>(EMPTY_PADS)
  const [canUndo, setCanUndo] = useState(false)

  const naturalW = image.width || 1024
  const naturalH = image.height || 1024

  const syncHasMask = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) {
      setHasMask(false)
      onMaskChange(false)
      return
    }
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data
    let painted = false
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] > 16) {
        painted = true
        break
      }
    }
    setHasMask(painted)
    onMaskChange(painted)
  }, [onMaskChange])

  const resetCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    canvas.width = naturalW
    canvas.height = naturalH
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    historyRef.current = []
    setCanUndo(false)
    setHasMask(false)
    onMaskChange(false)
  }, [naturalH, naturalW, onMaskChange])

  useEffect(() => {
    resetCanvas()
    setPads(EMPTY_PADS)
    onPadsChange(EMPTY_PADS)
  }, [image.id, onPadsChange, resetCanvas])

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const exportMask = useCallback(async () => {
    const src = canvasRef.current
    if (!src) return null
    const ctx = src.getContext('2d')
    if (!ctx) return null
    const data = ctx.getImageData(0, 0, src.width, src.height)
    const out = document.createElement('canvas')
    out.width = src.width
    out.height = src.height
    const outCtx = out.getContext('2d')
    if (!outCtx) return null
    const next = outCtx.createImageData(src.width, src.height)
    let painted = false
    for (let i = 0; i < data.data.length; i += 4) {
      const on = data.data[i + 3] > 16
      if (on) painted = true
      const v = on ? 255 : 0
      next.data[i] = v
      next.data[i + 1] = v
      next.data[i + 2] = v
      next.data[i + 3] = 255
    }
    if (!painted) return null
    outCtx.putImageData(next, 0, 0)
    return new Promise<Blob | null>((resolve) => {
      out.toBlob((blob) => resolve(blob), 'image/png')
    })
  }, [])

  useImperativeHandle(
    editorRef,
    () => ({
      exportMask,
      pads,
      hasMask,
    }),
    [exportMask, hasMask, pads],
  )

  function snapshot() {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    historyRef.current.push(ctx.getImageData(0, 0, canvas.width, canvas.height))
    if (historyRef.current.length > 30) historyRef.current.shift()
    setCanUndo(true)
  }

  function canvasPoint(event: ReactPointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    if (rect.width === 0 || rect.height === 0) return null
    return {
      x: ((event.clientX - rect.left) / rect.width) * canvas.width,
      y: ((event.clientY - rect.top) / rect.height) * canvas.height,
    }
  }

  function stroke(from: { x: number; y: number }, to: { x: number; y: number }) {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.strokeStyle = 'rgba(255, 72, 72, 0.88)'
    ctx.lineWidth = brush
    ctx.beginPath()
    ctx.moveTo(from.x, from.y)
    ctx.lineTo(to.x, to.y)
    ctx.stroke()
  }

  function onPointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (tool !== 'erase' || busy) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    snapshot()
    drawingRef.current = true
    const point = canvasPoint(event)
    if (!point) return
    lastRef.current = point
    stroke(point, point)
  }

  function onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!drawingRef.current) return
    const point = canvasPoint(event)
    if (!point || !lastRef.current) return
    stroke(lastRef.current, point)
    lastRef.current = point
  }

  function onPointerUp(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!drawingRef.current) return
    drawingRef.current = false
    lastRef.current = null
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      /* already released */
    }
    syncHasMask()
  }

  function undo() {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    const prev = historyRef.current.pop()
    if (!canvas || !ctx || !prev) return
    ctx.putImageData(prev, 0, 0)
    setCanUndo(historyRef.current.length > 0)
    syncHasMask()
  }

  function bump(side: keyof Pads, delta: number) {
    setPads((current) => {
      const nextVal = Math.max(0, Math.min(MAX_PAD, current[side] + delta))
      if (nextVal === current[side]) return current
      const next = { ...current, [side]: nextVal }
      onPadsChange(next)
      return next
    })
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    function onWheel(event: WheelEvent) {
      event.preventDefault()
      setBrush((value) => Math.min(128, Math.max(8, value + (event.deltaY > 0 ? -4 : 4))))
    }
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [tool])

  const totalW = naturalW + pads.left + pads.right
  const totalH = naturalH + pads.top + pads.bottom

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative flex items-center justify-center px-4 py-3">
        <div className="inline-flex items-center gap-1 rounded-full border border-border bg-panel p-1">
          <ToolButton
            label="擦除"
            icon={<Eraser className="h-4 w-4" aria-hidden="true" />}
            active={tool === 'erase'}
            disabled={busy}
            onClick={() => onTool('erase')}
          />
          <ToolButton
            label="扩图"
            icon={<Expand className="h-4 w-4" aria-hidden="true" />}
            active={tool === 'outpaint'}
            disabled={busy}
            onClick={() => onTool('outpaint')}
          />
          <ToolButton
            label="变清晰"
            icon={<Sparkles className="h-4 w-4" aria-hidden="true" />}
            active={false}
            disabled={busy}
            onClick={onEnhance}
          />
        </div>
        <button
          type="button"
          className="absolute right-4 grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-white/8 hover:text-fg"
          aria-label="关闭编辑"
          onClick={onClose}
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 items-center justify-center px-4 pb-3">
        <div className={`flex h-full w-full max-w-4xl items-center justify-center gap-3 ${tool === 'outpaint' ? '' : 'hidden'}`}>
          <PadControl
            label="左"
            value={pads.left}
            onMinus={() => bump('left', -PAD_STEP)}
            onPlus={() => bump('left', PAD_STEP)}
            min={0}
            max={MAX_PAD}
          />
          <div className="flex min-h-0 min-w-0 flex-1 flex-col items-center gap-3">
            <PadControl
              label="上"
              value={pads.top}
              onMinus={() => bump('top', -PAD_STEP)}
              onPlus={() => bump('top', PAD_STEP)}
              min={0}
              max={MAX_PAD}
            />
              <div
                className="relative w-full overflow-hidden rounded-2xl bg-[#6a6a6a]"
                style={{
                  aspectRatio: `${totalW} / ${totalH}`,
                  maxHeight: 'calc(100vh - 280px)',
                }}
              >
              <img
                src={imageUrl(image.id)}
                alt={image.prompt || '待扩图'}
                className="absolute object-fill"
                style={{
                  left: `${(pads.left / totalW) * 100}%`,
                  top: `${(pads.top / totalH) * 100}%`,
                  width: `${(naturalW / totalW) * 100}%`,
                  height: `${(naturalH / totalH) * 100}%`,
                }}
              />
            </div>
            <PadControl
              label="下"
              value={pads.bottom}
              onMinus={() => bump('bottom', -PAD_STEP)}
              onPlus={() => bump('bottom', PAD_STEP)}
              min={0}
              max={MAX_PAD}
            />
          </div>
          <PadControl
            label="右"
            value={pads.right}
            min={0}
            max={MAX_PAD}
            onMinus={() => bump('right', -PAD_STEP)}
            onPlus={() => bump('right', PAD_STEP)}
          />
        </div>

        <div className={`relative max-h-full max-w-full ${tool === 'outpaint' ? 'hidden' : ''}`}>
          <img
            src={imageUrl(image.id)}
            alt={image.prompt || '待编辑'}
            className="block max-h-[calc(100vh-260px)] max-w-full rounded-2xl object-contain"
            onLoad={(event) => {
              if (image.width && image.height) return
              const el = event.currentTarget
              const canvas = canvasRef.current
              if (!canvas || canvas.width === el.naturalWidth) return
              canvas.width = el.naturalWidth
              canvas.height = el.naturalHeight
            }}
          />
          <canvas
            ref={canvasRef}
            className={`absolute inset-0 h-full w-full touch-none rounded-2xl ${
              tool === 'erase' ? 'cursor-crosshair' : 'pointer-events-none'
            }`}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          />
        </div>
      </div>

      {tool === 'erase' && (
        <div className="flex items-center justify-center gap-3 px-4 pb-2 text-sm text-muted">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 hover:bg-white/8 hover:text-fg disabled:opacity-30"
            disabled={!canUndo || busy}
            onClick={undo}
          >
            <Undo2 className="h-4 w-4" aria-hidden="true" />
            撤销
          </button>
          <label className="inline-flex items-center gap-2">
            笔刷
            <input
              type="range"
              min={8}
              max={128}
              value={brush}
              aria-label="笔刷大小"
              onChange={(event) => setBrush(Number(event.target.value))}
            />
            <span className="w-8 tabular-nums">{brush}</span>
          </label>
        </div>
      )}
    </div>
  )
}

function ToolButton({
  label,
  icon,
  active,
  disabled,
  onClick,
}: {
  label: string
  icon: ReactNode
  active: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex h-10 items-center gap-1.5 rounded-full px-3.5 text-sm transition ${
        active ? 'bg-white text-bg' : 'text-fg hover:bg-white/8'
      } disabled:opacity-40`}
    >
      {icon}
      {label}
    </button>
  )
}

function PadControl({
  label,
  value,
  onMinus,
  onPlus,
  min = 0,
  max,
}: {
  label: string
  value: number
  onMinus: () => void
  onPlus: () => void
  min?: number
  max?: number
}) {
  return (
    <div className="flex flex-col items-center gap-1 text-xs text-muted">
      <span>{label}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className="grid h-8 w-8 place-items-center rounded-full hover:bg-white/8 hover:text-fg disabled:opacity-30"
          aria-label={`${label}减少`}
          disabled={value <= min}
          onClick={onMinus}
        >
          <Minus className="h-4 w-4" aria-hidden="true" />
        </button>
        <span className="w-10 text-center tabular-nums text-fg">{value}</span>
        <button
          type="button"
          className="grid h-8 w-8 place-items-center rounded-full hover:bg-white/8 hover:text-fg disabled:opacity-30"
          aria-label={`${label}增加`}
          disabled={max !== undefined && value >= max}
          onClick={onPlus}
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
