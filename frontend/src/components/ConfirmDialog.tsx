import { useEffect, useRef, type ReactNode } from 'react'

interface Props {
  title: string
  confirmLabel: string
  tone?: 'primary' | 'danger'
  busy: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
  children: ReactNode
}

// A native modal <dialog>: focus is trapped and Escape closes it. Mount it to open it, unmount it to close it.
export function ConfirmDialog({ title, confirmLabel, tone = 'primary', busy, error, onConfirm, onCancel, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
    return () => dialog?.close()
  }, [])

  return (
    <dialog
      ref={ref}
      className="confirm"
      aria-labelledby="confirm-title"
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onCancel()
      }}
      // Chrome can close a modal dialog without firing `cancel` (a second Escape): keep the parent state in step.
      onClose={() => {
        if (!busy) onCancel()
      }}
    >
      <h2 id="confirm-title">{title}</h2>
      <div className="confirm-body">{children}</div>
      {error && (
        <p role="alert" className="error" data-testid="confirm-error">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="button" className="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" className={tone === 'danger' ? 'danger' : 'primary'} onClick={onConfirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </dialog>
  )
}
