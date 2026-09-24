import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { Clapperboard, Eraser, Expand, Image as ImageIcon, Images, Plus, Sparkles, Trash2, Upload, X } from 'lucide-react'
import type { Aspect, CanvasDoc, CanvasItem, CanvasNodeKind, CanvasViewport, ImageRecord } from '../types'
import { imageUrl } from '../api'

export type BoardView = {
  panX: number
  panY: number
  scale: number
  width: number
  height: number
}

export type DropTarget = {
  x: number
  y: number
  fromId?: string
}

type NodeMenu = DropTarget & {
  title: string
  screenX: number
  screenY: number
}

type WireDrag = {
  fromId: string
  side: 'left' | 'right'
  x: number
  y: number
}

type Props = {
  canvas: CanvasDoc
  selectedId: string | null
  pendingId: string | null
  library: ImageRecord[]
  composer: ReactNode
  onSelect: (id: string | null) => void
  onOpen: (image: ImageRecord) => void
  onMove: (item: CanvasItem, x: number, y: number) => void
  onViewport: (viewport: CanvasViewport) => void
  onView: (view: BoardView) => void
  onCreateNode: (kind: CanvasNodeKind, target: DropTarget) => void
  onAddFromLibrary: (image: ImageRecord, target: DropTarget) => void
  onUpload: (file: File, target: DropTarget) => void
  onDelete: (item: CanvasItem) => void
  onDeleteEdge: (edgeId: string) => void
  onEdit: (image: ImageRecord, tool: 'erase' | 'outpaint' | 'enhance') => void
}

const ASPECT_RATIO: Record<string, [number, number]> = {
  auto: [1, 1],
  '1:1': [1, 1],
  '9:16': [9, 16],
  '16:9': [16, 9],
  '3:4': [3, 4],
  '4:3': [4, 3],
  '3:2': [3, 2],
  '2:3': [2, 3],
  '4:5': [4, 5],
  '5:4': [5, 4],
  '21:9': [21, 9],
}

export function cardSizeFromPixels(width: number | null, height: number | null, max = 360) {
  const sourceW = width && width > 0 ? width : 1024
  const sourceH = height && height > 0 ? height : 1024
  const scale = Math.min(1, max / sourceW)
  return {
    width: Math.max(96, Math.round(sourceW * scale)),
    height: Math.max(96, Math.round(sourceH * scale)),
  }
}

export function cardSizeFromAspect(aspect: string, max = 360) {
  const [w, h] = ASPECT_RATIO[aspect] ?? [1, 1]
  return { width: max, height: Math.max(96, Math.round((max * h) / w)) }
}

export function aspectFromSize(width: number, height: number): Aspect {
  if (width <= 0 || height <= 0) return '1:1'
  const ratio = width / height
  let best: Aspect = '1:1'
  let bestDiff = Number.POSITIVE_INFINITY
  for (const key of Object.keys(ASPECT_RATIO)) {
    if (key === 'auto') continue
    const [w, h] = ASPECT_RATIO[key]
    const diff = Math.abs(Math.log(ratio) - Math.log(w / h))
    if (diff < bestDiff) {
      best = key as Aspect
      bestDiff = diff
    }
  }
  return best
}

function curve(x1: number, y1: number, x2: number, y2: number) {
  const bend = Math.max(80, Math.abs(x2 - x1) * 0.45)
  const sign = x2 >= x1 ? 1 : -1
  return `M ${x1} ${y1} C ${x1 + sign * bend} ${y1}, ${x2 - sign * bend} ${y2}, ${x2} ${y2}`
}

export function CanvasView({
  canvas,
  selectedId,
  pendingId,
  library,
  composer,
  onSelect,
  onOpen,
  onMove,
  onViewport,
  onView,
  onCreateNode,
  onAddFromLibrary,
  onUpload,
  onDelete,
  onDeleteEdge,
  onEdit,
}: Props) {
  const boardRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [pan, setPan] = useState({ x: canvas.viewport.x || 0, y: canvas.viewport.y || 0 })
  const [scale, setScale] = useState(canvas.viewport.scale || 1)
  const [libraryTarget, setLibraryTarget] = useState<DropTarget | null>(null)
  const [menu, setMenu] = useState<NodeMenu | null>(null)
  const [wire, setWire] = useState<WireDrag | null>(null)
  const [hint, setHint] = useState<{ x: number; y: number } | null>(null)
  const [drag, setDrag] = useState<{ id: string; x: number; y: number } | null>(null)
  const panDrag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null)
  const cardDrag = useRef<{ id: string; x: number; y: number; origX: number; origY: number; moved: boolean } | null>(null)
  const dropRef = useRef<DropTarget | null>(null)
  const saveTimer = useRef<number | null>(null)
  const wireListen = useRef<{ move: (event: PointerEvent) => void; up: (event: PointerEvent) => void } | null>(null)
  const panRef = useRef(pan)
  const scaleRef = useRef(scale)
  const onViewportRef = useRef(onViewport)
  panRef.current = pan
  scaleRef.current = scale
  onViewportRef.current = onViewport
  const edges = canvas.edges ?? []

  useEffect(() => {
    setPan({ x: canvas.viewport.x || 0, y: canvas.viewport.y || 0 })
    setScale(canvas.viewport.scale || 1)
    setMenu(null)
    setLibraryTarget(null)
    setWire(null)
  }, [canvas.id])

  useEffect(() => {
    const el = boardRef.current
    if (!el) return
    const report = () => {
      const rect = el.getBoundingClientRect()
      onView({ panX: pan.x, panY: pan.y, scale, width: rect.width, height: rect.height })
    }
    report()
    const observer = new ResizeObserver(report)
    observer.observe(el)
    return () => observer.disconnect()
  }, [onView, pan.x, pan.y, scale])

  useEffect(() => {
    const el = boardRef.current
    if (!el) return
    function onWheel(event: WheelEvent) {
      event.preventDefault()
      const rect = el!.getBoundingClientRect()
      const cursorX = event.clientX - rect.left
      const cursorY = event.clientY - rect.top
      const current = scaleRef.current
      const origin = panRef.current
      const next = Math.min(3, Math.max(0.15, current * (event.deltaY < 0 ? 1.08 : 0.92)))
      const worldX = (cursorX - origin.x) / current
      const worldY = (cursorY - origin.y) / current
      const moved = { x: cursorX - worldX * next, y: cursorY - worldY * next }
      panRef.current = moved
      scaleRef.current = next
      setPan(moved)
      setScale(next)
      scheduleSave(moved, next)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [canvas.id])

  useEffect(() => {
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current)
      if (wireListen.current) {
        window.removeEventListener('pointermove', wireListen.current.move)
        window.removeEventListener('pointerup', wireListen.current.up)
      }
    }
  }, [])

  function scheduleSave(origin: { x: number; y: number }, nextScale: number) {
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      onViewportRef.current({ x: origin.x, y: origin.y, scale: nextScale })
    }, 400)
  }

  function clientToWorld(clientX: number, clientY: number) {
    const rect = boardRef.current?.getBoundingClientRect()
    const left = clientX - (rect?.left ?? 0)
    const top = clientY - (rect?.top ?? 0)
    return {
      x: (left - panRef.current.x) / (scaleRef.current || 1),
      y: (top - panRef.current.y) / (scaleRef.current || 1),
      screenX: left,
      screenY: top,
    }
  }

  function openMenu(next: NodeMenu) {
    const rect = boardRef.current?.getBoundingClientRect()
    const width = rect?.width ?? 800
    const height = rect?.height ?? 600
    setMenu({
      ...next,
      screenX: Math.min(Math.max(8, next.screenX), Math.max(8, width - 196)),
      screenY: Math.min(Math.max(8, next.screenY), Math.max(8, height - 240)),
    })
    setLibraryTarget(null)
  }

  function positionOf(item: CanvasItem) {
    if (drag?.id === item.id) return { x: drag.x, y: drag.y }
    return { x: item.x, y: item.y }
  }

  function portOf(item: CanvasItem, side: 'left' | 'right') {
    const pos = positionOf(item)
    return {
      x: side === 'left' ? pos.x : pos.x + item.width,
      y: pos.y + item.height / 2,
    }
  }

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 && event.button !== 1) return
    const target = event.target as HTMLElement
    if (target.closest('[data-card-controls]') || target.closest('[data-port]')) return
    setMenu(null)
    const card = target.closest('[data-card-id]') as HTMLElement | null
    if (event.button === 1 || !card) {
      panDrag.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y }
      event.currentTarget.setPointerCapture(event.pointerId)
      return
    }
    const item = canvas.items.find((entry) => entry.id === card.dataset.cardId)
    if (!item) return
    cardDrag.current = {
      id: item.id,
      x: event.clientX,
      y: event.clientY,
      origX: item.x,
      origY: item.y,
      moved: false,
    }
    setDrag({ id: item.id, x: item.x, y: item.y })
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (canvas.items.length === 0 && !wire) {
      const point = clientToWorld(event.clientX, event.clientY)
      setHint({ x: point.screenX, y: point.screenY })
    }
    if (panDrag.current) {
      const next = {
        x: panDrag.current.panX + event.clientX - panDrag.current.x,
        y: panDrag.current.panY + event.clientY - panDrag.current.y,
      }
      panRef.current = next
      setPan(next)
      return
    }
    const current = cardDrag.current
    if (!current) return
    const dx = (event.clientX - current.x) / scale
    const dy = (event.clientY - current.y) / scale
    if (Math.hypot(event.clientX - current.x, event.clientY - current.y) > 3) current.moved = true
    setDrag({ id: current.id, x: current.origX + dx, y: current.origY + dy })
  }

  function onPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (panDrag.current) {
      const moved = Math.hypot(event.clientX - panDrag.current.x, event.clientY - panDrag.current.y)
      if (moved < 4) onSelect(null)
      scheduleSave(panRef.current, scaleRef.current)
      panDrag.current = null
    }
    const current = cardDrag.current
    cardDrag.current = null
    if (!current) return
    const item = canvas.items.find((entry) => entry.id === current.id)
    if (current.moved && item && drag) onMove(item, drag.x, drag.y)
    else onSelect(current.id)
    setDrag(null)
  }

  function onDoubleClick(event: ReactPointerEvent<HTMLDivElement>) {
    const target = event.target as HTMLElement
    if (target.closest('[data-card-id]') || target.closest('[data-port]')) return
    const point = clientToWorld(event.clientX, event.clientY)
    openMenu({
      title: '新建节点',
      x: point.x,
      y: point.y,
      screenX: point.screenX,
      screenY: point.screenY,
    })
  }

  function startWire(event: ReactPointerEvent<HTMLButtonElement>, item: CanvasItem, side: 'left' | 'right') {
    event.stopPropagation()
    event.preventDefault()
    const origin = portOf(item, side)
    setMenu(null)
    setWire({ fromId: item.id, side, x: origin.x, y: origin.y })
    const move = (pointer: PointerEvent) => {
      const point = clientToWorld(pointer.clientX, pointer.clientY)
      setWire({ fromId: item.id, side, x: point.x, y: point.y })
    }
    const up = (pointer: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      wireListen.current = null
      setWire(null)
      const point = clientToWorld(pointer.clientX, pointer.clientY)
      openMenu({
        title: '添加节点',
        x: point.x,
        y: point.y,
        screenX: point.screenX,
        screenY: point.screenY,
        fromId: item.id,
      })
    }
    if (wireListen.current) {
      window.removeEventListener('pointermove', wireListen.current.move)
      window.removeEventListener('pointerup', wireListen.current.up)
    }
    wireListen.current = { move, up }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  function chooseKind(kind: CanvasNodeKind) {
    if (!menu) return
    onCreateNode(kind, { x: menu.x, y: menu.y, fromId: menu.fromId })
    setMenu(null)
  }

  function chooseLibrary() {
    if (!menu) return
    setLibraryTarget({ x: menu.x, y: menu.y, fromId: menu.fromId })
    setMenu(null)
  }

  function chooseUpload() {
    if (!menu) return
    dropRef.current = { x: menu.x, y: menu.y, fromId: menu.fromId }
    setMenu(null)
    fileRef.current?.click()
  }

  const selected = canvas.items.find((item) => item.id === selectedId) ?? null
  const selectedPos = selected ? positionOf(selected) : null
  const boardRect = boardRef.current?.getBoundingClientRect()
  const composerLeft = selectedPos ? selectedPos.x * scale + pan.x : 0
  const composerTop = selectedPos ? (selectedPos.y + (selected?.height ?? 0)) * scale + pan.y + 12 : 0
  const composerWidth = Math.min(440, Math.max(280, (boardRect?.width ?? 800) - 24))
  const composerX = Math.min(Math.max(12, composerLeft), Math.max(12, (boardRect?.width ?? 800) - composerWidth - 12))
  const composerY = Math.min(composerTop, Math.max(12, (boardRect?.height ?? 600) - 168))

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={boardRef}
        className="absolute inset-0 cursor-grab overflow-hidden active:cursor-grabbing"
        style={{
          backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.16) 1px, transparent 1px)',
          backgroundSize: `${24 * scale}px ${24 * scale}px`,
          backgroundPosition: `${pan.x}px ${pan.y}px`,
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={onDoubleClick}
        onPointerLeave={() => setHint(null)}
      >
        <div
          className="absolute top-0 left-0"
          style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, transformOrigin: '0 0' }}
        >
          <svg className="pointer-events-none absolute overflow-visible" style={{ left: -8000, top: -8000, width: 16000, height: 16000 }}>
            <g transform="translate(8000 8000)">
              {edges.map((edge) => {
                const from = canvas.items.find((item) => item.id === edge.from_item_id)
                const to = canvas.items.find((item) => item.id === edge.to_item_id)
                if (!from || !to) return null
                const start = portOf(from, 'right')
                const end = portOf(to, 'left')
                return (
                  <path
                    key={edge.id}
                    d={curve(start.x, start.y, end.x, end.y)}
                    fill="none"
                    stroke="#7eb6ff"
                    strokeWidth={2.5}
                  />
                )
              })}
              {wire &&
                (() => {
                  const from = canvas.items.find((item) => item.id === wire.fromId)
                  if (!from) return null
                  const start = portOf(from, wire.side)
                  return (
                    <path d={curve(start.x, start.y, wire.x, wire.y)} fill="none" stroke="#7eb6ff" strokeWidth={2.5} />
                  )
                })()}
            </g>
          </svg>
          {edges.map((edge) => {
            const from = canvas.items.find((item) => item.id === edge.from_item_id)
            const to = canvas.items.find((item) => item.id === edge.to_item_id)
            if (!from || !to) return null
            const start = portOf(from, 'right')
            const end = portOf(to, 'left')
            return (
              <button
                key={`${edge.id}-remove`}
                type="button"
                data-card-controls="true"
                title="断开连线"
                className="group/edge absolute grid h-8 w-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full text-white"
                style={{ left: (start.x + end.x) / 2, top: (start.y + end.y) / 2, zIndex: 40 }}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => onDeleteEdge(edge.id)}
              >
                <span className="grid h-5 w-5 place-items-center rounded-full bg-[#1c2430] opacity-0 ring-1 ring-[#7eb6ff] transition group-hover/edge:opacity-100">
                  <X className="h-3 w-3" aria-hidden="true" />
                </span>
              </button>
            )
          })}
          {canvas.items.map((item) => {
            const pos = positionOf(item)
            const active = item.id === selectedId
            const image = item.image
            const showPorts = active || wire?.fromId === item.id
            return (
              <div
                key={item.id}
                data-card-id={item.id}
                className="group absolute"
                style={{ left: pos.x, top: pos.y - 28, width: item.width, height: item.height + 28, zIndex: item.z }}
                onDoubleClick={(event) => {
                  event.stopPropagation()
                  if (image) onOpen(image)
                }}
              >
                <div className="flex h-7 items-center justify-between gap-2 px-0.5 text-xs text-fg/80">
                  <span className="truncate">{item.title || (item.node_kind === 'video' ? '视频' : '图片')}</span>
                  {active && (
                    <span className="flex shrink-0 items-center gap-0.5" data-card-controls="true">
                      {image && image.media_type !== 'video' && (
                        <>
                          <button type="button" title="擦除" className="grid h-6 w-6 place-items-center rounded-md text-muted hover:bg-white/10 hover:text-fg" onPointerDown={(event) => event.stopPropagation()} onClick={() => onEdit(image, 'erase')}>
                            <Eraser className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                          <button type="button" title="扩图" className="grid h-6 w-6 place-items-center rounded-md text-muted hover:bg-white/10 hover:text-fg" onPointerDown={(event) => event.stopPropagation()} onClick={() => onEdit(image, 'outpaint')}>
                            <Expand className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                          <button type="button" title="变清晰" className="grid h-6 w-6 place-items-center rounded-md text-muted hover:bg-white/10 hover:text-fg" onPointerDown={(event) => event.stopPropagation()} onClick={() => onEdit(image, 'enhance')}>
                            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        </>
                      )}
                      <button type="button" title="删除" className="grid h-6 w-6 place-items-center rounded-md text-red-300 hover:bg-white/10" onPointerDown={(event) => event.stopPropagation()} onClick={() => onDelete(item)}>
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    </span>
                  )}
                </div>
                <div className="relative" style={{ height: item.height }}>
                  <button
                    type="button"
                    data-port="left"
                    aria-label="向左连线"
                    className={`absolute top-1/2 -left-3 z-10 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full bg-white text-black shadow transition ${showPorts ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
                    onPointerDown={(event) => startWire(event, item, 'left')}
                  >
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                  <div
                    className={`h-full overflow-hidden rounded-2xl bg-[#141414] shadow-[0_16px_40px_rgba(0,0,0,0.35)] ${
                      active ? 'ring-2 ring-white' : 'ring-1 ring-white/15'
                    } ${image ? '' : 'border border-dashed border-white/25'}`}
                  >
                    {image?.media_type === 'video' ? (
                      <video
                        data-card-controls="true"
                        src={imageUrl(image.id)}
                        className="h-full w-full bg-black object-contain"
                        controls
                        playsInline
                        onPointerDown={(event) => event.stopPropagation()}
                      />
                    ) : image ? (
                      <img src={imageUrl(image.id)} alt={image.prompt || item.title} draggable={false} className="h-full w-full object-cover" />
                    ) : (
                      <div className="grid h-full place-items-center text-white/35">
                        {item.node_kind === 'video' ? <Clapperboard className="h-8 w-8" /> : <ImageIcon className="h-8 w-8" />}
                      </div>
                    )}
                    {pendingId === item.id && (
                      <div className="absolute inset-x-0 bottom-0 grid h-8 place-items-center bg-black/55 text-xs text-white">生成中</div>
                    )}
                  </div>
                  <button
                    type="button"
                    data-port="right"
                    aria-label="向右连线"
                    className={`absolute top-1/2 -right-3 z-10 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full bg-white text-black shadow transition ${showPorts ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
                    onPointerDown={(event) => startWire(event, item, 'right')}
                  >
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
        {canvas.items.length === 0 && hint && !menu && (
          <div className="pointer-events-none absolute z-10" style={{ left: hint.x + 16, top: hint.y + 12 }}>
            <p className="text-sm text-white">双击画布</p>
            <p className="text-xs text-muted">创建节点</p>
          </div>
        )}
      </div>
      {menu && (
        <div
          className="absolute z-30 w-44 overflow-hidden rounded-2xl border border-white/10 bg-[#1b1b1b] p-1.5 shadow-[0_16px_50px_rgba(0,0,0,0.45)]"
          style={{ left: menu.screenX, top: menu.screenY }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <p className="px-2.5 py-1.5 text-xs text-muted">{menu.title}</p>
          <button type="button" className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm hover:bg-white/10" onClick={() => chooseKind('image')}>
            <ImageIcon className="h-4 w-4" aria-hidden="true" />
            图片
          </button>
          <button type="button" className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm hover:bg-white/10" onClick={() => chooseKind('video')}>
            <Clapperboard className="h-4 w-4" aria-hidden="true" />
            视频
          </button>
          <div className="my-1 h-px bg-white/10" />
          <button type="button" className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm hover:bg-white/10" onClick={chooseLibrary}>
            <Images className="h-4 w-4" aria-hidden="true" />
            从图库添加
          </button>
          <button type="button" className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-sm hover:bg-white/10" onClick={chooseUpload}>
            <Upload className="h-4 w-4" aria-hidden="true" />
            本地上传
          </button>
        </div>
      )}
      {selected && composer && (
        <div
          className="absolute z-20"
          style={{ left: composerX, top: composerY, width: composerWidth }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {composer}
        </div>
      )}
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif,video/mp4,video/webm,video/quicktime"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          const target = dropRef.current
          event.target.value = ''
          if (file && target) onUpload(file, target)
        }}
      />
      {libraryTarget && (
        <aside className="absolute top-3 right-3 bottom-3 z-20 flex w-64 flex-col overflow-hidden rounded-2xl border border-border bg-panel shadow-xl">
          <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs text-muted">
            <span>放到这个位置</span>
            <button type="button" className="rounded-md p-1 hover:bg-white/10 hover:text-fg" onClick={() => setLibraryTarget(null)} aria-label="关闭图库">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {library.length === 0 ? (
              <p className="px-1 py-6 text-center text-xs text-muted">图库还是空的</p>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                {library.map((image) => (
                  <button
                    key={image.id}
                    type="button"
                    className="overflow-hidden rounded-xl bg-black"
                    onClick={() => {
                      onAddFromLibrary(image, libraryTarget)
                      setLibraryTarget(null)
                    }}
                  >
                    {image.media_type === 'video' ? (
                      <video src={imageUrl(image.id)} className="aspect-square w-full object-cover" muted />
                    ) : (
                      <img src={imageUrl(image.id)} alt={image.prompt || '图库图片'} className="aspect-square w-full object-cover" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  )
}
