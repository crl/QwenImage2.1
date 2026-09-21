import { useEffect, useRef, useState } from 'react'
import { Archive, ArchiveRestore, ChevronDown, ImageIcon, Pencil, Plus, Trash2, WifiOff, type LucideIcon } from 'lucide-react'
import type { ConversationSummary, Health } from '../types'

type RowAction = {
  label: string
  icon: LucideIcon
  onClick: () => void
  danger?: boolean
}

type Props = {
  conversations: ConversationSummary[]
  archivedConversations: ConversationSummary[]
  activeId?: string
  health: Health | null
  onNew: () => void
  onOpenLibrary: () => void
  onOpenConversation: (id: string) => void
  onArchive: (id: string) => void
  onUnarchive: (id: string) => void
  onDeleteArchived: (item: ConversationSummary) => void
  onRename: (id: string, title: string) => void
}

export function Sidebar({
  conversations,
  archivedConversations,
  activeId,
  health,
  onNew,
  onOpenLibrary,
  onOpenConversation,
  onArchive,
  onUnarchive,
  onDeleteArchived,
  onRename,
}: Props) {
  const [showArchived, setShowArchived] = useState(false)

  return (
    <aside className="flex h-full w-[272px] shrink-0 flex-col border-r border-border bg-sidebar">
      <div className="px-3 pt-4 pb-2">
        <button
          type="button"
          onClick={onOpenLibrary}
          className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-[15px] font-semibold text-fg transition hover:bg-white/5"
        >
          <span className="grid h-7 w-7 place-items-center rounded-lg border border-border">
            <ImageIcon className="h-4 w-4" aria-hidden="true" />
          </span>
          Qwen Image
        </button>
      </div>
      <div className="px-3">
        <button
          type="button"
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-xl bg-white/5 px-3 py-2.5 text-sm font-medium text-fg transition hover:bg-white/10"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          新对话
        </button>
        <button
          type="button"
          onClick={onOpenLibrary}
          className={`mt-1 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm transition hover:bg-white/5 ${
            !activeId ? 'bg-white/8 text-fg' : 'text-muted'
          }`}
        >
          <ImageIcon className="h-4 w-4" aria-hidden="true" />
          图库
        </button>
      </div>
      <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-2">
        <p className="px-2 pb-2 text-xs font-medium tracking-wide text-muted uppercase">对话</p>
        {conversations.length === 0 ? (
          <p className="px-2 text-sm text-muted">还没有对话</p>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((item) => (
              <ConversationRow
                key={item.id}
                item={item}
                active={activeId === item.id}
                actions={[{ label: '归档对话', icon: Archive, onClick: () => onArchive(item.id) }]}
                onOpen={() => onOpenConversation(item.id)}
                onRename={(title) => onRename(item.id, title)}
              />
            ))}
          </ul>
        )}
        {archivedConversations.length > 0 && (
          <div className="mt-4">
            <button
              type="button"
              onClick={() => setShowArchived((open) => !open)}
              className="flex w-full items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium tracking-wide text-muted uppercase transition hover:bg-white/5 hover:text-fg"
            >
              <ChevronDown className={`h-3.5 w-3.5 transition ${showArchived ? '' : '-rotate-90'}`} aria-hidden="true" />
              已归档
              <span className="ml-auto normal-case">{archivedConversations.length}</span>
            </button>
            {showArchived && (
              <ul className="mt-0.5 space-y-0.5">
                {archivedConversations.map((item) => (
                  <ConversationRow
                    key={item.id}
                    item={item}
                    active={activeId === item.id}
                    actions={[
                      { label: '取消归档', icon: ArchiveRestore, onClick: () => onUnarchive(item.id) },
                      { label: '删除对话', icon: Trash2, onClick: () => onDeleteArchived(item), danger: true },
                    ]}
                    onOpen={() => onOpenConversation(item.id)}
                    onRename={(title) => onRename(item.id, title)}
                  />
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <div className="border-t border-border px-4 py-3">
        <div className="flex items-center gap-2 text-xs">
          {health?.ok ? (
            <span className="h-2 w-2 rounded-full bg-emerald-400" aria-hidden="true" />
          ) : (
            <WifiOff className="h-3.5 w-3.5 text-red-400" aria-hidden="true" />
          )}
          <span className={health?.ok ? 'text-muted' : 'text-red-300'}>
            {health?.ok ? `ComfyUI ${health.comfyui_version || ''} 已连接` : 'ComfyUI 未连接'}
          </span>
        </div>
      </div>
    </aside>
  )
}

function ConversationRow({
  item,
  active,
  actions,
  onOpen,
  onRename,
}: {
  item: ConversationSummary
  active: boolean
  actions: RowAction[]
  onOpen: () => void
  onRename: (title: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(item.title)
  const inputRef = useRef<HTMLInputElement>(null)
  const skipCommit = useRef(false)
  const actionCount = actions.length + 1

  useEffect(() => {
    setDraft(item.title)
  }, [item.title])

  useEffect(() => {
    if (!editing) return
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [editing])

  function startRename() {
    setDraft(item.title)
    setEditing(true)
  }

  function cancelRename() {
    skipCommit.current = true
    setDraft(item.title)
    setEditing(false)
  }

  function commitRename() {
    if (skipCommit.current) {
      skipCommit.current = false
      return
    }
    const next = draft.trim()
    setEditing(false)
    if (!next || next === item.title) {
      setDraft(item.title)
      return
    }
    onRename(next)
  }

  return (
    <li className="group relative">
      {editing ? (
        <input
          ref={inputRef}
          value={draft}
          maxLength={80}
          aria-label="对话标题"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commitRename}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              commitRename()
            }
            if (event.key === 'Escape') {
              event.preventDefault()
              cancelRename()
            }
          }}
          className="w-full rounded-lg bg-white/10 py-2 pr-2 pl-3 text-sm text-fg outline-none ring-1 ring-white/20"
        />
      ) : (
        <>
          <button
            type="button"
            title="双击重命名"
            onClick={onOpen}
            onDoubleClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              startRename()
            }}
            className={`w-full truncate rounded-lg py-2 pl-3 text-left text-sm transition hover:bg-white/5 ${
              actionCount > 2 ? 'pr-[4.75rem]' : actionCount > 1 ? 'pr-16' : 'pr-9'
            } ${active ? 'bg-white/10 text-fg' : 'text-muted'}`}
          >
            {item.title}
          </button>
          <div className="absolute top-1/2 right-1 flex -translate-y-1/2">
            <button
              type="button"
              aria-label="重命名"
              title="重命名"
              onClick={(event) => {
                event.stopPropagation()
                startRename()
              }}
              className="grid h-7 w-7 place-items-center rounded-md text-muted opacity-70 transition group-hover:opacity-100 hover:bg-white/10 hover:text-fg"
            >
              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            {actions.map((action) => (
              <button
                key={action.label}
                type="button"
                aria-label={action.label}
                title={action.label}
                onClick={(event) => {
                  event.stopPropagation()
                  action.onClick()
                }}
                className={`grid h-7 w-7 place-items-center rounded-md opacity-70 transition group-hover:opacity-100 hover:bg-white/10 ${
                  action.danger ? 'text-red-300 hover:text-red-200' : 'text-muted hover:text-fg'
                }`}
              >
                <action.icon className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            ))}
          </div>
        </>
      )}
    </li>
  )
}
