import { useEffect, useRef, type ReactNode } from 'react'

type Props = {
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  busy?: boolean
  preview?: ReactNode
  onCancel: () => void
  onConfirm: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = '确定删除',
  busy = false,
  preview,
  onCancel,
  onConfirm,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape' && !busy) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, busy, onCancel])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-6" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
      <button type="button" className="absolute inset-0 cursor-default" aria-label="取消" onClick={busy ? undefined : onCancel} />
      <div className="relative z-10 w-full max-w-sm rounded-3xl border border-border bg-panel p-5 shadow-2xl">
        <h2 id="confirm-title" className="text-lg font-semibold text-fg">
          {title}
        </h2>
        <p className="mt-1 text-sm text-muted">{description}</p>
        {preview}
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            disabled={busy}
            className="rounded-full px-4 py-2 text-sm text-fg hover:bg-white/8 disabled:opacity-50"
            onClick={onCancel}
          >
            取消
          </button>
          <button
            type="button"
            disabled={busy}
            className="rounded-full bg-red-500 px-4 py-2 text-sm font-medium text-white hover:bg-red-400 disabled:opacity-50"
            onClick={onConfirm}
          >
            {busy ? '删除中…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
