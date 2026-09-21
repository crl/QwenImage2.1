import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUp, ImagePlus, Square, X } from 'lucide-react'
import type { KeyboardEvent } from 'react'
import { ASPECTS, type Aspect, type Quality } from '../types'

type Props = {
  prompt: string
  aspect: Aspect
  quality: Quality
  transparent: boolean
  files: File[]
  busy: boolean
  disabled?: boolean
  placeholder?: string
  onPrompt: (value: string) => void
  onAspect: (value: Aspect) => void
  onQuality: (value: Quality) => void
  onTransparent: (value: boolean) => void
  onFiles: (files: File[]) => void
  onSubmit: () => void
  onStop: () => void
}

type Mention = {
  start: number
  query: string
}

export function Composer({
  prompt,
  aspect,
  quality,
  transparent,
  files,
  busy,
  disabled,
  placeholder = '描述你想生成或修改的图像',
  onPrompt,
  onAspect,
  onQuality,
  onTransparent,
  onFiles,
  onSubmit,
  onStop,
}: Props) {
  const areaRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const filesRef = useRef(files)
  filesRef.current = files
  const [mention, setMention] = useState<Mention | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)

  useEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [prompt])

  const options = useMemo(() => {
    if (!mention || files.length < 2) return []
    const query = mention.query.trim().toLowerCase()
    return files
      .map((file, index) => ({
        index,
        file,
        label: `图${index + 1}`,
      }))
      .filter((item) => {
        if (!query) return true
        return item.label.toLowerCase().includes(query) || item.file.name.toLowerCase().includes(query)
      })
  }, [files, mention])

  useEffect(() => {
    setActiveIndex(0)
  }, [mention?.query, files.length])

  useEffect(() => {
    if (files.length < 2) setMention(null)
  }, [files.length])

  function addImageFiles(incoming: File[]) {
    if (incoming.length === 0) return
    const images = incoming.filter((file) => file.type.startsWith('image/')).map((file, index) => {
      if (file.name && file.name !== 'image.png' && file.name !== 'blob') return file
      const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')
      return new File([file], `paste-${Date.now()}-${index}.${ext}`, { type: file.type || 'image/png' })
    })
    if (images.length === 0) return
    onFiles([...filesRef.current, ...images].slice(0, 10))
  }

  function addFiles(list: FileList | File[] | null) {
    if (!list) return
    addImageFiles(Array.from(list))
  }

  useEffect(() => {
    function onPaste(event: ClipboardEvent) {
      const target = event.target
      if (target instanceof HTMLInputElement) return
      if (target instanceof HTMLTextAreaElement && target !== areaRef.current) return
      const data = event.clipboardData
      if (!data) return
      const fromItems = Array.from(data.items)
        .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
        .map((item) => item.getAsFile())
        .filter((file): file is File => Boolean(file))
      const fromFiles = Array.from(data.files).filter((file) => file.type.startsWith('image/'))
      const images = fromItems.length > 0 ? fromItems : fromFiles
      if (images.length === 0) return
      event.preventDefault()
      addImageFiles(images)
      areaRef.current?.focus()
      const text = data.getData('text/plain')
      if (text && target === areaRef.current) {
        const el = areaRef.current
        const start = el?.selectionStart ?? prompt.length
        const end = el?.selectionEnd ?? prompt.length
        onPrompt(prompt.slice(0, start) + text + prompt.slice(end))
      }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [onFiles, onPrompt, prompt])

  function syncMention(text: string, caret: number) {
    if (filesRef.current.length < 2) {
      setMention(null)
      return
    }
    const before = text.slice(0, caret)
    const match = before.match(/(^|[\s\n])@([^\s@]*)$/)
    if (!match) {
      setMention(null)
      return
    }
    setMention({
      start: caret - match[2].length - 1,
      query: match[2],
    })
  }

  function insertMention(index: number) {
    const el = areaRef.current
    if (!mention || !el) return
    const caret = el.selectionStart ?? prompt.length
    const token = `@图${index + 1} `
    const next = prompt.slice(0, mention.start) + token + prompt.slice(caret)
    onPrompt(next)
    setMention(null)
    requestAnimationFrame(() => {
      const pos = mention.start + token.length
      el.focus()
      el.setSelectionRange(pos, pos)
    })
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (mention && options.length > 0) {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActiveIndex((current) => (current + 1) % options.length)
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveIndex((current) => (current - 1 + options.length) % options.length)
        return
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault()
        insertMention(options[activeIndex]?.index ?? 0)
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        setMention(null)
        return
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      if (!busy && prompt.trim()) onSubmit()
    }
  }

  const showMention = mention !== null && files.length >= 2

  return (
    <div className="mx-auto w-full max-w-3xl">
      {files.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2 px-1">
          {files.map((file, index) => (
            <Attachment
              key={`${file.name}-${index}`}
              file={file}
              label={files.length > 1 ? `图${index + 1}` : undefined}
              onRemove={() => onFiles(files.filter((_, i) => i !== index))}
            />
          ))}
        </div>
      )}
      <div className="relative">
        {showMention && (
          <div
            className="absolute inset-x-0 bottom-full z-20 mb-2 overflow-hidden rounded-2xl border border-border bg-panel shadow-[0_12px_40px_rgba(0,0,0,0.35)]"
            role="listbox"
            aria-label="选择参考图"
          >
            {options.length === 0 ? (
              <p className="px-3 py-2.5 text-sm text-muted">当前参考图中没有匹配项</p>
            ) : (
              options.map((item, optionIndex) => (
                <button
                  key={`${item.file.name}-${item.index}`}
                  type="button"
                  role="option"
                  aria-selected={optionIndex === activeIndex}
                  className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition ${
                    optionIndex === activeIndex ? 'bg-white/10 text-fg' : 'text-fg hover:bg-white/6'
                  }`}
                  onMouseEnter={() => setActiveIndex(optionIndex)}
                  onMouseDown={(event) => {
                    event.preventDefault()
                    insertMention(item.index)
                  }}
                >
                  <MentionThumb file={item.file} />
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                </button>
              ))
            )}
          </div>
        )}
        <div className="rounded-[28px] border border-border bg-elevated p-2 shadow-[0_8px_30px_rgba(0,0,0,0.25)]">
          <label className="sr-only" htmlFor="prompt">
            图像描述
          </label>
          <textarea
            id="prompt"
            ref={areaRef}
            value={prompt}
            disabled={disabled}
            onChange={(e) => {
              onPrompt(e.target.value)
              syncMention(e.target.value, e.target.selectionStart ?? e.target.value.length)
            }}
            onKeyUp={(e) => syncMention(e.currentTarget.value, e.currentTarget.selectionStart ?? 0)}
            onClick={(e) => syncMention(e.currentTarget.value, e.currentTarget.selectionStart ?? 0)}
            onKeyDown={onKeyDown}
            placeholder={files.length > 1 ? `${placeholder}，输入 @ 选择图片` : placeholder}
            rows={1}
            className="max-h-52 min-h-12 w-full resize-none bg-transparent px-4 pt-3 pb-1 text-[15px] leading-6 text-fg outline-none placeholder:text-muted"
          />
          <div className="flex items-center gap-1 px-2 pb-1">
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                addFiles(e.target.files)
                e.target.value = ''
              }}
            />
            <button
              type="button"
              className="grid h-9 w-9 place-items-center rounded-full text-muted transition hover:bg-white/8 hover:text-fg"
              aria-label="上传参考图"
              onClick={() => fileRef.current?.click()}
            >
              <ImagePlus className="h-5 w-5" aria-hidden="true" />
            </button>
            <select
              value={aspect}
              aria-label="画面比例"
              onChange={(e) => onAspect(e.target.value as Aspect)}
              className="h-9 rounded-full bg-transparent px-2 text-xs text-muted outline-none hover:text-fg"
            >
              {ASPECTS.map((item) => (
                <option key={item} value={item} className="bg-bg">
                  {item}
                </option>
              ))}
            </select>
            <select
              value={quality}
              aria-label="清晰度"
              onChange={(e) => onQuality(e.target.value as Quality)}
              className="h-9 rounded-full bg-transparent px-2 text-xs text-muted outline-none hover:text-fg"
            >
              <option value="1k" className="bg-bg">
                1K
              </option>
              <option value="2k" className="bg-bg">
                2K
              </option>
            </select>
            <button
              type="button"
              onClick={() => onTransparent(!transparent)}
              className={`h-9 rounded-full px-3 text-xs transition ${
                transparent ? 'bg-white text-bg' : 'text-muted hover:bg-white/8 hover:text-fg'
              }`}
              aria-pressed={transparent}
            >
              透明底
            </button>
            <div className="ml-auto">
              {busy ? (
                <button
                  type="button"
                  onClick={onStop}
                  className="grid h-9 w-9 place-items-center rounded-full bg-fg text-bg"
                  aria-label="停止生成"
                >
                  <Square className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onSubmit}
                  disabled={disabled || !prompt.trim()}
                  className="grid h-9 w-9 place-items-center rounded-full bg-fg text-bg transition disabled:cursor-not-allowed disabled:opacity-30"
                  aria-label="发送"
                >
                  <ArrowUp className="h-4 w-4" aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
      <p className="mt-2 text-center text-[11px] text-muted">
        {files.length > 1 ? '输入 @ 可从当前参考图中选择' : 'Qwen-Image-2.1 · 本地 ComfyUI · 后续消息会基于上一张图继续编辑'}
      </p>
    </div>
  )
}

function FilePreview({ file, className }: { file: File; className?: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const next = URL.createObjectURL(file)
    setUrl(next)
    setReady(false)
    setFailed(false)
    return () => URL.revokeObjectURL(next)
  }, [file])

  return (
    <div className={`relative overflow-hidden bg-white/8 ${className ?? ''}`}>
      {!ready && (
        <div className="absolute inset-0 grid place-items-center text-muted" aria-hidden="true">
          <ImagePlus className="h-4 w-4 opacity-50" />
        </div>
      )}
      {url && !failed && (
        <img
          src={url}
          alt=""
          className={`h-full w-full object-cover ${ready ? '' : 'hidden'}`}
          onLoad={() => setReady(true)}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  )
}

function MentionThumb({ file }: { file: File }) {
  return <FilePreview file={file} className="h-9 w-9 shrink-0 rounded-lg" />
}

function Attachment({ file, label, onRemove }: { file: File; label?: string; onRemove: () => void }) {
  return (
    <div className="w-16">
      <div className="relative h-16 w-16 overflow-hidden rounded-xl">
        <FilePreview file={file} className="h-full w-full" />
        <button
          type="button"
          className="absolute top-1 right-1 grid h-5 w-5 place-items-center rounded-full bg-black/70 text-white"
          aria-label={`移除 ${file.name}`}
          onClick={onRemove}
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>
      {label ? <p className="mt-1 text-center text-[11px] text-muted">{label}</p> : null}
    </div>
  )
}
