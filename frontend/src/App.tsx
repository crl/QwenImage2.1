import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { ChatView } from './components/ChatView'
import { Composer } from './components/Composer'
import { ConfirmDialog } from './components/ConfirmDialog'
import { ImageEditor, type ImageEditorHandle } from './components/ImageEditor'
import { LibraryView } from './components/LibraryView'
import { Lightbox } from './components/Lightbox'
import { Sidebar } from './components/Sidebar'
import {
  createConversation,
  deleteConversation,
  deleteImage,
  getConversation,
  getHealth,
  getLibrary,
  hideImageFromChat,
  imageUrl,
  interrupt,
  listConversations,
  renameConversation,
  sendMessage,
  setConversationArchived,
} from './api'
import type { Aspect, Conversation, ConversationSummary, EditMode, Health, ImageRecord, Pads, Quality, StudioEvent } from './types'

type PendingDelete =
  | { type: 'image'; image: ImageRecord; scope: 'chat' | 'library' }
  | { type: 'conversation'; conversation: ConversationSummary }

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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

function Studio() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [health, setHealth] = useState<Health | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [archivedConversations, setArchivedConversations] = useState<ConversationSummary[]>([])
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [library, setLibrary] = useState<ImageRecord[]>([])
  const [prompt, setPrompt] = useState('')
  const [aspect, setAspect] = useState<Aspect>('1:1')
  const [quality, setQuality] = useState<Quality>('1k')
  const [transparent, setTransparent] = useState(false)
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

  const busy = useMemo(
    () => conversation?.messages.some((item) => item.status === 'generating') ?? false,
    [conversation],
  )

  const refreshLists = useCallback(async () => {
    const [items, archivedItems, images] = await Promise.all([
      listConversations(false),
      listConversations(true),
      getLibrary(),
    ])
    setConversations(items)
    setArchivedConversations(archivedItems)
    setLibrary(images)
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
    sourceRef.current?.close()
    sourceRef.current = null
    if (!id) {
      setConversation(null)
      return
    }
    let cancelled = false
    getConversation(id)
      .then((data) => {
        if (!cancelled) {
          setConversation(data)
          setError(null)
        }
      })
      .catch((err: Error) => setError(err.message))

    const source = new EventSource(`/api/conversations/${id}/events`)
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
        if (!current || current.id !== id) return current
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
  }, [id, refreshLists])

  useEffect(() => {
    const el = threadRef.current
    if (el && !editor) el.scrollTop = el.scrollHeight
  }, [conversation, editor])

  useEffect(() => {
    if (editor && id && editor.image.conversation_id !== id) {
      setEditor(null)
    }
  }, [id, editor])

  function openEditor(image: ImageRecord, tool: EditMode = 'erase') {
    setLightbox(null)
    setFiles([])
    setHasMask(false)
    setPads(EMPTY_PADS)
    setEditor({ image, tool })
    if (id !== image.conversation_id) navigate(`/c/${image.conversation_id}`)
  }

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
      let conversationId = id || session?.image.conversation_id
      if (!conversationId) {
        const created = await createConversation(prompt.trim().slice(0, 36))
        conversationId = created.id
        navigate(`/c/${created.id}`)
      }
      const result = await sendMessage(conversationId, {
        prompt: prompt.trim(),
        aspect,
        quality: session?.tool === 'enhance' ? '2k' : quality,
        transparent: session ? false : transparent,
        files: session ? [] : files,
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
      setError(err instanceof Error ? err.message : '发送失败')
    }
  }

  async function handleStop() {
    await interrupt(id)
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

  return (
    <div className="flex h-full bg-bg text-fg">
      <Sidebar
        conversations={conversations}
        archivedConversations={archivedConversations}
        activeId={id}
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
        <div ref={threadRef} className={`flex min-h-0 flex-1 flex-col ${editor ? 'overflow-hidden' : 'overflow-y-auto'}`}>
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
        <div className="px-4 pt-2 pb-5">
          <Composer
            prompt={prompt}
            aspect={aspect}
            quality={quality}
            transparent={transparent}
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
                  : id
                    ? '继续描述修改，可粘贴或上传参考图'
                    : '描述你想生成的图像，可粘贴参考图'
            }
            onPrompt={setPrompt}
            onAspect={setAspect}
            onQuality={setQuality}
            onTransparent={setTransparent}
            onFiles={setFiles}
            onSubmit={() => void handleSubmit()}
            onStop={() => void handleStop()}
          />
        </div>
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
            : pendingDelete?.scope === 'chat'
              ? '从对话中移除这张图？'
              : '确定删除这张图片？'
        }
        description={
          pendingDelete?.type === 'conversation'
            ? '删除后无法撤销，这个对话以及其中生成的图片都会从本机移除。'
            : pendingDelete?.scope === 'chat'
              ? '对话里会显示为已删除，图库中仍会保留。'
              : '删除后无法撤销。图库会去掉这张图，对话里会显示为已删除。'
        }
        confirmLabel={pendingDelete?.type === 'image' && pendingDelete.scope === 'chat' ? '从对话移除' : '确定删除'}
        busy={deleting}
        preview={
          pendingDelete?.type === 'image' ? (
            <div className="checker mt-4 overflow-hidden rounded-2xl">
              <img
                src={imageUrl(pendingDelete.image.id)}
                alt={pendingDelete.image.prompt || '即将删除的图像'}
                className="max-h-40 w-full object-contain"
              />
            </div>
          ) : pendingDelete?.type === 'conversation' ? (
            <p className="mt-4 truncate rounded-2xl bg-white/5 px-3 py-2 text-sm text-fg">{pendingDelete.conversation.title}</p>
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
