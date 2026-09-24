import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { CanvasView, aspectFromSize, cardSizeFromAspect, cardSizeFromPixels, type BoardView, type DropTarget } from './components/CanvasView'
import { ChatView } from './components/ChatView'
import { Composer } from './components/Composer'
import { ConfirmDialog } from './components/ConfirmDialog'
import { ImageEditor, type ImageEditorHandle } from './components/ImageEditor'
import { LibraryView } from './components/LibraryView'
import { Lightbox } from './components/Lightbox'
import { Sidebar } from './components/Sidebar'
import {
  addCanvasEdge,
  addCanvasItem,
  createCanvas,
  createConversation,
  deleteCanvas,
  deleteCanvasEdge,
  deleteCanvasItem,
  deleteConversation,
  deleteImage,
  getCanvas,
  getConversation,
  getHealth,
  getLibrary,
  hideImageFromChat,
  imageUrl,
  interrupt,
  listCanvases,
  listConversations,
  renameConversation,
  sendMessage,
  setConversationArchived,
  updateCanvas,
  updateCanvasItem,
  uploadCanvasMedia,
} from './api'
import type { Aspect, CanvasDoc, CanvasItem, CanvasNodeKind, CanvasSummary, CanvasViewport, Conversation, ConversationSummary, EditMode, Health, ImageRecord, MediaMode, Pads, Quality, StudioEvent, VideoQuality } from './types'

type PendingDelete =
  | { type: 'image'; image: ImageRecord; scope: 'chat' | 'library' }
  | { type: 'conversation'; conversation: ConversationSummary }
  | { type: 'canvas'; canvas: CanvasSummary }

type Place = { canvasId: string; itemId: string }

type EditorSession = {
  image: ImageRecord
  tool: EditMode
}

const EMPTY_PADS: Pads = { left: 0, top: 0, right: 0, bottom: 0 }

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Studio />} />
        <Route path="/c/:id" element={<Studio />} />
        <Route path="/canvas/:canvasId" element={<Studio />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

function Studio() {
  const { id, canvasId } = useParams()
  const navigate = useNavigate()
  const [health, setHealth] = useState<Health | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [archivedConversations, setArchivedConversations] = useState<ConversationSummary[]>([])
  const [canvases, setCanvases] = useState<CanvasSummary[]>([])
  const [canvas, setCanvas] = useState<CanvasDoc | null>(null)
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)
  const [pendingPlace, setPendingPlace] = useState<string | null>(null)
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [library, setLibrary] = useState<ImageRecord[]>([])
  const [prompt, setPrompt] = useState('')
  const [aspect, setAspect] = useState<Aspect>('1:1')
  const [quality, setQuality] = useState<Quality>('1k')
  const [videoQuality, setVideoQuality] = useState<VideoQuality>('720p')
  const [transparent, setTransparent] = useState(false)
  const [mediaMode, setMediaMode] = useState<MediaMode>('image')
  const [videoSeconds, setVideoSeconds] = useState(5)
  const [files, setFiles] = useState<File[]>([])
  const [lightbox, setLightbox] = useState<ImageRecord | null>(null)
  const [editor, setEditor] = useState<EditorSession | null>(null)
  const [hasMask, setHasMask] = useState(false)
  const [pads, setPads] = useState<Pads>(EMPTY_PADS)
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sourceRef = useRef<EventSource | null>(null)
  const threadRef = useRef<HTMLDivElement>(null)
  const editorRef = useRef<ImageEditorHandle | null>(null)
  const viewRef = useRef<BoardView>({ panX: 0, panY: 0, scale: 1, width: 800, height: 600 })
  const placeRef = useRef<Place | null>(null)
  const canvasIdRef = useRef(canvasId)
  canvasIdRef.current = canvasId
  const activeCanvas = canvas && canvas.id === canvasId ? canvas : null
  const streamConversationId = canvasId ? activeCanvas?.conversation_id : id

  const busy = useMemo(
    () => conversation?.messages.some((item) => item.status === 'generating') ?? false,
    [conversation],
  )

  const refreshLists = useCallback(async () => {
    const [items, archivedItems, images, boards] = await Promise.all([
      listConversations(false),
      listConversations(true),
      getLibrary(),
      listCanvases(),
    ])
    setConversations(items)
    setArchivedConversations(archivedItems)
    setLibrary(images)
    setCanvases(boards)
  }, [])

  useEffect(() => {
    let alive = true
    async function tick() {
      try {
        const next = await getHealth()
        if (alive) setHealth(next)
      } catch {
        if (alive) setHealth({ ok: false, error: '无法连接后端' })
      }
    }
    tick()
    const timer = window.setInterval(tick, 5000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    refreshLists().catch((err: Error) => setError(err.message))
  }, [refreshLists])

  useEffect(() => {
    if (!canvasId) return
    let cancelled = false
    getCanvas(canvasId)
      .then((data) => {
        if (!cancelled) {
          setCanvas(data)
          setError(null)
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [canvasId])

  useEffect(() => {
    sourceRef.current?.close()
    sourceRef.current = null
    if (!streamConversationId) {
      setConversation(null)
      return
    }
    let cancelled = false
    getConversation(streamConversationId)
      .then((data) => {
        if (!cancelled) {
          setConversation(data)
          setError(null)
        }
      })
      .catch((err: Error) => setError(err.message))

    const source = new EventSource(`/api/conversations/${streamConversationId}/events`)
    sourceRef.current = source
    source.onmessage = (event) => {
      const payload = JSON.parse(event.data) as StudioEvent
      if (payload.type === 'snapshot') {
        setConversation((current) => {
          if (current && current.messages.length > payload.conversation.messages.length) return current
          return payload.conversation
        })
        return
      }
      setConversation((current) => {
        if (!current || current.id !== streamConversationId) return current
        if (payload.type === 'progress') {
          return mapMessage(current, payload.message_id, (message) => ({
            ...message,
            status: 'generating',
            progress: payload.value,
            progress_max: payload.max,
          }))
        }
        if (payload.type === 'preview') {
          return mapMessage(current, payload.message_id, (message) => ({
            ...message,
            preview: payload.data_url,
          }))
        }
        if (payload.type === 'done') {
          const place = placeRef.current
          if (place && canvasIdRef.current === place.canvasId) {
            void (async () => {
              const image = payload.images.find((item) => item.id && !item.deleted)
              if (image) {
                const size = cardSizeFromPixels(image.width, image.height)
                const kind: CanvasNodeKind = image.media_type === 'video' ? 'video' : 'image'
                await updateCanvasItem(place.canvasId, place.itemId, {
                  image_id: image.id,
                  node_kind: kind,
                  width: size.width,
                  height: size.height,
                })
              }
              const fresh = await getCanvas(place.canvasId)
              setCanvas((board) => (board?.id === fresh.id ? fresh : board))
              if (placeRef.current?.itemId === place.itemId) {
                placeRef.current = null
                setPendingPlace(null)
              }
            })().catch((err: Error) => setError(err.message))
          }
          const next = {
            ...current,
            messages: current.messages.map((message) =>
              message.id === payload.message.id
                ? { ...payload.message, images: payload.images, ref_images: message.ref_images }
                : message,
            ),
          }
          refreshLists().catch(() => undefined)
          return next
        }
        if (payload.type === 'error') {
          placeRef.current = null
          setPendingPlace(null)
          return mapMessage(current, payload.message_id, (message) =>
            payload.message ? { ...payload.message, images: message.images } : { ...message, status: 'error', error: payload.error },
          )
        }
        return current
      })
    }
    return () => {
      cancelled = true
      source.close()
    }
  }, [streamConversationId, refreshLists])

  useEffect(() => {
    const el = threadRef.current
    if (el && !editor) el.scrollTop = el.scrollHeight
  }, [conversation, editor])

  useEffect(() => {
    if (editor && !canvasId && id && editor.image.conversation_id !== id) {
      setEditor(null)
    }
  }, [id, canvasId, editor])

  function openEditor(image: ImageRecord, tool: EditMode = 'erase') {
    if (image.media_type === 'video') return
    setLightbox(null)
    setFiles([])
    setHasMask(false)
    setPads(EMPTY_PADS)
    setEditor({ image, tool })
    if (!canvasId && id !== image.conversation_id) navigate(`/c/${image.conversation_id}`)
  }

  const onBoardView = useCallback((view: BoardView) => {
    viewRef.current = view
  }, [])

  async function handleSubmit(session: EditorSession | null = editor) {
    if (session == null && !prompt.trim()) return
    if (!health?.ok) {
      setError('请先启动 Comfy Desktop，并确认 8188 端口可用')
      return
    }
    let mask: Blob | null = null
    let nextPads = pads
    if (session?.tool === 'erase') {
      mask = (await editorRef.current?.exportMask()) ?? null
      if (!mask) {
        setError('请先涂抹要修改的区域')
        return
      }
    }
    if (session?.tool === 'outpaint') {
      nextPads = editorRef.current?.pads ?? pads
      if (nextPads.left + nextPads.top + nextPads.right + nextPads.bottom <= 0) {
        setError('请先扩展画布')
        return
      }
    }
    setError(null)
    try {
      const onCanvas = Boolean(canvasId && activeCanvas)
      let conversationId = onCanvas ? activeCanvas!.conversation_id : id || session?.image.conversation_id
      if (!conversationId) {
        const created = await createConversation(prompt.trim().slice(0, 36))
        conversationId = created.id
        navigate(`/c/${created.id}`)
      }
      let nextFiles = session ? [] : files
      let outputMode: MediaMode = mediaMode
      if (onCanvas && activeCanvas) {
        if (session) {
          const source =
            activeCanvas.items.find((item) => item.id === selectedItemId && item.image?.id === session.image.id) ??
            activeCanvas.items.find((item) => item.image?.id === session.image.id)
          if (!source) {
            setError('找不到原图节点')
            return
          }
          const size = cardSizeFromPixels(source.image?.width ?? null, source.image?.height ?? null)
          const created = await addCanvasItem(activeCanvas.id, {
            node_kind: 'image',
            x: source.x + source.width + 48,
            y: source.y,
            width: size.width,
            height: size.height,
          })
          const edge = await addCanvasEdge(activeCanvas.id, { from_item_id: source.id, to_item_id: created.id })
          setCanvas((current) =>
            current
              ? { ...current, items: [...current.items, created], edges: [...(current.edges ?? []), edge] }
              : current,
          )
          placeRef.current = { canvasId: activeCanvas.id, itemId: created.id }
          setPendingPlace(created.id)
          setSelectedItemId(created.id)
        } else {
          const node = activeCanvas.items.find((item) => item.id === selectedItemId)
          if (!node) {
            setError('先双击画布，创建一个图片或视频节点')
            return
          }
          outputMode = node.node_kind === 'video' || node.image?.media_type === 'video' ? 'video' : 'image'
          placeRef.current = { canvasId: activeCanvas.id, itemId: node.id }
          setPendingPlace(node.id)
          if (nextFiles.length === 0) {
            const incoming = (activeCanvas.edges ?? []).filter((edge) => edge.to_item_id === node.id)
            for (const edge of incoming) {
              const source = activeCanvas.items.find((item) => item.id === edge.from_item_id)
              if (!source?.image || source.image.media_type === 'video') continue
              const response = await fetch(imageUrl(source.image.id))
              if (response.ok) {
                const blob = await response.blob()
                nextFiles = [new File([blob], 'reference.png', { type: blob.type || 'image/png' })]
              }
              break
            }
          }
        }
      }
      const result = await sendMessage(conversationId, {
        prompt: prompt.trim(),
        aspect,
        quality: session?.tool === 'enhance' ? '2k' : outputMode === 'video' ? videoQuality : quality,
        transparent: session || outputMode === 'video' ? false : transparent,
        files: nextFiles,
        mediaMode: session ? 'image' : outputMode,
        videoSeconds: session ? undefined : outputMode === 'video' ? videoSeconds : undefined,
        chain: onCanvas ? false : undefined,
        editMode: session?.tool,
        sourceImageId: session?.image.id,
        mask,
        pads: session?.tool === 'outpaint' ? nextPads : undefined,
      })
      setPrompt('')
      setFiles([])
      setEditor(null)
      setConversation((current) => {
        const base = current ?? {
          id: conversationId!,
          title: prompt.trim().slice(0, 36),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          messages: [],
        }
        const existing = new Set(base.messages.map((item) => item.id))
        const messages = [...base.messages]
        if (!existing.has(result.user.id)) messages.push(result.user)
        if (!existing.has(result.assistant.id)) messages.push(result.assistant)
        return { ...base, messages }
      })
      await refreshLists()
    } catch (err) {
      placeRef.current = null
      setPendingPlace(null)
      setError(err instanceof Error ? err.message : '发送失败')
    }
  }

  async function handleStop() {
    await interrupt(activeCanvas?.conversation_id || id)
  }

  async function handleNewCanvas() {
    try {
      const created = await createCanvas()
      setCanvases((current) => [created, ...current.filter((item) => item.id !== created.id)])
      setEditor(null)
      navigate(`/canvas/${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建画布失败')
    }
  }

  async function handleRenameCanvas(boardId: string, title: string) {
    try {
      const updated = await updateCanvas(boardId, { title })
      setCanvases((current) => current.map((item) => (item.id === boardId ? { ...item, title } : item)))
      setCanvas((current) => (current?.id === boardId ? { ...current, title: updated.title } : current))
    } catch (err) {
      setError(err instanceof Error ? err.message : '重命名失败')
    }
  }

  async function handleMoveItem(item: CanvasItem, x: number, y: number) {
    if (!activeCanvas) return
    setCanvas((current) =>
      current
        ? { ...current, items: current.items.map((entry) => (entry.id === item.id ? { ...entry, x, y } : entry)) }
        : current,
    )
    try {
      await updateCanvasItem(activeCanvas.id, item.id, { x, y })
    } catch (err) {
      setError(err instanceof Error ? err.message : '移动失败')
    }
  }

  function rememberNode(item: CanvasItem, edge?: { id: string; canvas_id: string; from_item_id: string; to_item_id: string }) {
    setCanvas((current) =>
      current
        ? {
            ...current,
            items: [...current.items.filter((entry) => entry.id !== item.id), item],
            edges: edge ? [...(current.edges ?? []).filter((entry) => entry.id !== edge.id), edge] : current.edges ?? [],
          }
        : current,
    )
    setSelectedItemId(item.id)
    applyNodeMedia(item)
  }

  function applyNodeMedia(item: CanvasItem) {
    const video = item.node_kind === 'video' || item.image?.media_type === 'video'
    setMediaMode(video ? 'video' : 'image')
    setAspect(aspectFromSize(item.width, item.height))
    if (video) setTransparent(false)
  }

  function handleSelectNode(id: string | null) {
    setSelectedItemId(id)
    if (!id || !activeCanvas) return
    const item = activeCanvas.items.find((entry) => entry.id === id)
    if (!item) return
    applyNodeMedia(item)
  }

  function handleAspect(next: Aspect) {
    setAspect(next)
    if (!canvasId || editor || !activeCanvas || !selectedItemId) return
    const item = activeCanvas.items.find((entry) => entry.id === selectedItemId)
    if (!item) return
    const video = item.node_kind === 'video' || item.image?.media_type === 'video'
    const frame = next === 'auto' ? (video ? '16:9' : '1:1') : next
    const size = cardSizeFromAspect(frame)
    const x = item.x + (item.width - size.width) / 2
    const y = item.y + (item.height - size.height) / 2
    setCanvas((current) =>
      current
        ? {
            ...current,
            items: current.items.map((entry) =>
              entry.id === item.id ? { ...entry, x, y, width: size.width, height: size.height } : entry,
            ),
          }
        : current,
    )
    updateCanvasItem(activeCanvas.id, item.id, { x, y, width: size.width, height: size.height }).catch((err: Error) =>
      setError(err.message),
    )
  }

  async function handleCreateNode(kind: CanvasNodeKind, target: DropTarget) {
    if (!activeCanvas) return
    const size = kind === 'video' ? cardSizeFromAspect('16:9') : { width: 360, height: 360 }
    try {
      const item = await addCanvasItem(activeCanvas.id, {
        node_kind: kind,
        x: target.x - size.width / 2,
        y: target.y - size.height / 2,
        width: size.width,
        height: size.height,
      })
      const edge = target.fromId
        ? await addCanvasEdge(activeCanvas.id, { from_item_id: target.fromId, to_item_id: item.id })
        : undefined
      rememberNode(item, edge)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建节点失败')
    }
  }

  async function handlePlaceMedia(image: ImageRecord, target: DropTarget) {
    if (!activeCanvas) return
    const size = cardSizeFromPixels(image.width, image.height)
    const kind: CanvasNodeKind = image.media_type === 'video' ? 'video' : 'image'
    try {
      const item = await addCanvasItem(activeCanvas.id, {
        image_id: image.id,
        node_kind: kind,
        x: target.x - size.width / 2,
        y: target.y - size.height / 2,
        width: size.width,
        height: size.height,
      })
      const edge = target.fromId
        ? await addCanvasEdge(activeCanvas.id, { from_item_id: target.fromId, to_item_id: item.id })
        : undefined
      rememberNode(item, edge)
    } catch (err) {
      setError(err instanceof Error ? err.message : '添加失败')
    }
  }

  async function handleUploadMedia(file: File, target: DropTarget) {
    if (!activeCanvas) return
    try {
      const image = await uploadCanvasMedia(activeCanvas.id, file)
      await handlePlaceMedia(image, target)
      await refreshLists()
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败')
    }
  }

  async function handleDeleteCanvasItem(item: CanvasItem) {
    if (!activeCanvas) return
    try {
      await deleteCanvasItem(activeCanvas.id, item.id)
      setCanvas((current) =>
        current
          ? {
              ...current,
              items: current.items.filter((entry) => entry.id !== item.id),
              edges: (current.edges ?? []).filter((edge) => edge.from_item_id !== item.id && edge.to_item_id !== item.id),
            }
          : current,
      )
      setSelectedItemId((current) => (current === item.id ? null : current))
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  async function handleDeleteEdge(edgeId: string) {
    if (!activeCanvas) return
    try {
      await deleteCanvasEdge(activeCanvas.id, edgeId)
      setCanvas((current) =>
        current ? { ...current, edges: (current.edges ?? []).filter((edge) => edge.id !== edgeId) } : current,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '断开连线失败')
    }
  }

  function saveViewport(viewport: CanvasViewport) {
    if (!canvasId) return
    updateCanvas(canvasId, { viewport }).catch(() => undefined)
  }

  async function handleArchive(cid: string) {
    try {
      await setConversationArchived(cid, true)
      if (id === cid) navigate('/')
      await refreshLists()
    } catch (err) {
      setError(err instanceof Error ? err.message : '归档失败')
    }
  }

  async function handleUnarchive(cid: string) {
    try {
      await setConversationArchived(cid, false)
      await refreshLists()
    } catch (err) {
      setError(err instanceof Error ? err.message : '取消归档失败')
    }
  }

  async function handleRename(cid: string, title: string) {
    try {
      await renameConversation(cid, title)
      setConversation((current) => (current?.id === cid ? { ...current, title } : current))
      await refreshLists()
    } catch (err) {
      setError(err instanceof Error ? err.message : '重命名失败')
    }
  }

  async function handleConfirmDelete() {
    if (!pendingDelete || deleting) return
    setDeleting(true)
    setError(null)
    try {
      if (pendingDelete.type === 'image') {
        const image = pendingDelete.image
        if (pendingDelete.scope === 'chat') {
          await hideImageFromChat(image.id)
        } else {
          await deleteImage(image.id)
        }
        setLightbox((current) => (current?.id === image.id ? null : current))
        setEditor((current) => (current?.image.id === image.id ? null : current))
        setConversation((current) => {
          if (!current) return current
          return {
            ...current,
            messages: current.messages.map((message) => ({
              ...message,
              images: message.images.map((item) => (item.id === image.id ? { ...item, deleted: true } : item)),
              ref_images: message.ref_images.map((item) => (item.id === image.id ? { ...item, deleted: true } : item)),
            })),
          }
        })
      } else if (pendingDelete.type === 'canvas') {
        const boardId = pendingDelete.canvas.id
        await deleteCanvas(boardId)
        setCanvases((current) => current.filter((item) => item.id !== boardId))
        if (canvasId === boardId) {
          setCanvas(null)
          navigate('/')
        }
      } else {
        const conversationId = pendingDelete.conversation.id
        await deleteConversation(conversationId)
        setLightbox((current) => (current?.conversation_id === conversationId ? null : current))
        setEditor((current) => (current?.image.conversation_id === conversationId ? null : current))
        if (id === conversationId) {
          setConversation(null)
          navigate('/')
        }
      }
      setPendingDelete(null)
      await refreshLists()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const selectedNode =
    canvasId && !editor && activeCanvas
      ? activeCanvas.items.find((item) => item.id === selectedItemId) ?? null
      : null

  const composer = (
    <Composer
      prompt={prompt}
      aspect={aspect}
      quality={quality}
      videoQuality={videoQuality}
      transparent={transparent}
      mediaMode={mediaMode}
      lockMediaMode={Boolean(selectedNode)}
      videoSeconds={videoSeconds}
      files={files}
      busy={busy}
      disabled={health?.ok === false}
      editMode={editor?.tool}
      allowEmpty={
        editor?.tool === 'erase'
          ? hasMask
          : editor?.tool === 'outpaint'
            ? pads.left + pads.top + pads.right + pads.bottom > 0
            : false
      }
      placeholder={
        editor?.tool === 'erase'
          ? '描述要改成什么，留空则抹掉填回周围'
          : editor?.tool === 'outpaint'
            ? '可选描述扩展后的内容，留空则自然外延'
            : mediaMode === 'video'
              ? canvasId
                ? '描述镜头。连入的图片会作为首帧，结果填进这个节点'
                : id
                  ? '描述镜头运动与画面变化，可上传首帧参考图'
                  : '描述你想生成的视频，可上传首帧参考图'
              : canvasId
                ? '描述画面。连入的图片会作为参考，结果填进这个节点'
                : id
                  ? '继续描述修改，可粘贴或上传参考图'
                  : '描述你想生成的图像，可粘贴参考图'
      }
      onPrompt={setPrompt}
      onAspect={handleAspect}
      onQuality={setQuality}
      onVideoQuality={setVideoQuality}
      onTransparent={setTransparent}
      onMediaMode={(mode) => {
        if (selectedNode) return
        setMediaMode(mode)
        if (mode === 'video') {
          setTransparent(false)
          if (aspect === '1:1') setAspect('16:9')
        }
      }}
      onVideoSeconds={setVideoSeconds}
      onFiles={setFiles}
      onSubmit={() => void handleSubmit()}
      onStop={() => void handleStop()}
    />
  )

  return (
    <div className="flex h-full bg-bg text-fg">
      <Sidebar
        conversations={conversations}
        archivedConversations={archivedConversations}
        canvases={canvases}
        activeId={id}
        activeCanvasId={canvasId}
        libraryActive={!id && !canvasId}
        health={health}
        onNew={() => {
          setEditor(null)
          navigate('/')
        }}
        onOpenLibrary={() => {
          setEditor(null)
          navigate('/')
        }}
        onOpenConversation={(cid) => navigate(`/c/${cid}`)}
        onArchive={(cid) => void handleArchive(cid)}
        onUnarchive={(cid) => void handleUnarchive(cid)}
        onDeleteArchived={(item) => setPendingDelete({ type: 'conversation', conversation: item })}
        onRename={(cid, title) => void handleRename(cid, title)}
        onNewCanvas={() => void handleNewCanvas()}
        onOpenCanvas={(boardId) => {
          setEditor(null)
          navigate(`/canvas/${boardId}`)
        }}
        onRenameCanvas={(boardId, title) => void handleRenameCanvas(boardId, title)}
        onDeleteCanvas={(item) => setPendingDelete({ type: 'canvas', canvas: item })}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        {!health?.ok && health !== null && (
          <div className="border-b border-red-500/20 bg-red-500/10 px-4 py-2 text-center text-sm text-red-200">
            未连接到 ComfyUI。请先打开 Comfy Desktop，默认地址 http://127.0.0.1:8188
          </div>
        )}
        {error && (
          <div className="border-b border-red-500/20 bg-red-500/10 px-4 py-2 text-center text-sm text-red-200">
            {error}
          </div>
        )}
        <div ref={threadRef} className={`flex min-h-0 flex-1 flex-col ${editor || canvasId ? 'overflow-hidden' : 'overflow-y-auto'}`}>
          {editor ? (
            <ImageEditor
              image={editor.image}
              tool={editor.tool}
              busy={busy}
              editorRef={editorRef}
              onTool={(tool) => setEditor((current) => (current ? { ...current, tool } : current))}
              onClose={() => setEditor(null)}
              onEnhance={() => void handleSubmit({ image: editor.image, tool: 'enhance' })}
              onMaskChange={setHasMask}
              onPadsChange={setPads}
            />
          ) : canvasId ? (
            activeCanvas ? (
              <CanvasView
                canvas={activeCanvas}
                selectedId={selectedItemId}
                pendingId={pendingPlace}
                library={library}
                composer={composer}
                onSelect={handleSelectNode}
                onOpen={setLightbox}
                onMove={(item, x, y) => void handleMoveItem(item, x, y)}
                onViewport={saveViewport}
                onView={onBoardView}
                onCreateNode={(kind, target) => void handleCreateNode(kind, target)}
                onAddFromLibrary={(image, target) => void handlePlaceMedia(image, target)}
                onUpload={(file, target) => void handleUploadMedia(file, target)}
                onDelete={(item) => void handleDeleteCanvasItem(item)}
                onDeleteEdge={(edgeId) => void handleDeleteEdge(edgeId)}
                onEdit={(image, tool) => openEditor(image, tool)}
              />
            ) : (
              <div className="grid flex-1 place-items-center text-sm text-muted">正在打开画布</div>
            )
          ) : id ? (
            <ChatView
              conversation={conversation}
              onOpenImage={setLightbox}
              onDeleteImage={(image) => setPendingDelete({ type: 'image', image, scope: 'chat' })}
              onEditImage={(image) => openEditor(image)}
            />
          ) : (
            <LibraryView
              images={library}
              onOpen={setLightbox}
              onDelete={(image) => setPendingDelete({ type: 'image', image, scope: 'library' })}
            />
          )}
        </div>
        {!(canvasId && !editor) && <div className="px-4 pt-2 pb-5">{composer}</div>}
      </main>
      <Lightbox
        image={lightbox}
        onClose={() => setLightbox(null)}
        onEdit={(image) => openEditor(image)}
        onDelete={(image) => setPendingDelete({ type: 'image', image, scope: id ? 'chat' : 'library' })}
      />
      <ConfirmDialog
        open={pendingDelete !== null}
        title={
          pendingDelete?.type === 'conversation'
            ? '确定删除这个对话？'
            : pendingDelete?.type === 'canvas'
              ? '确定删除这个画布？'
            : pendingDelete?.scope === 'chat'
              ? '从对话中移除这张图？'
              : '确定删除这张图片？'
        }
        description={
          pendingDelete?.type === 'conversation'
            ? '删除后无法撤销，这个对话以及其中生成的图片都会从本机移除。'
            : pendingDelete?.type === 'canvas'
              ? '画布上的排列会被移除。已经生成的图片仍留在图库里。'
            : pendingDelete?.scope === 'chat'
              ? '对话里会显示为已删除，图库中仍会保留。'
              : '删除后无法撤销。图库会去掉这张图，对话里会显示为已删除。'
        }
        confirmLabel={pendingDelete?.type === 'image' && pendingDelete.scope === 'chat' ? '从对话移除' : '确定删除'}
        busy={deleting}
        preview={
          pendingDelete?.type === 'image' ? (
            <div className="checker mt-4 overflow-hidden rounded-2xl">
              {pendingDelete.image.media_type === 'video' ? (
                <video
                  src={imageUrl(pendingDelete.image.id)}
                  className="max-h-40 w-full object-contain"
                  muted
                  playsInline
                />
              ) : (
                <img
                  src={imageUrl(pendingDelete.image.id)}
                  alt={pendingDelete.image.prompt || '即将删除的图像'}
                  className="max-h-40 w-full object-contain"
                />
              )}
            </div>
          ) : pendingDelete?.type === 'conversation' ? (
            <p className="mt-4 truncate rounded-2xl bg-white/5 px-3 py-2 text-sm text-fg">{pendingDelete.conversation.title}</p>
          ) : pendingDelete?.type === 'canvas' ? (
            <p className="mt-4 truncate rounded-2xl bg-white/5 px-3 py-2 text-sm text-fg">{pendingDelete.canvas.title}</p>
          ) : null
        }
        onCancel={() => {
          if (!deleting) setPendingDelete(null)
        }}
        onConfirm={() => void handleConfirmDelete()}
      />
    </div>
  )
}

function mapMessage(conversation: Conversation, messageId: string, updater: (message: Conversation['messages'][number]) => Conversation['messages'][number]) {
  return {
    ...conversation,
    messages: conversation.messages.map((message) => (message.id === messageId ? updater(message) : message)),
  }
}
