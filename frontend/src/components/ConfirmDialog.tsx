import { useEffect, useRef, type ReactNode } from 'react'

interface Props {
  title: string
  confirmLabel: string
  tone?: 'primary' | 'danger'
  busy: boolean
  error: string | null
  /** Why the action can no longer be confirmed (the server moved on). Shown in the dialog; disables the confirm button. */
  unavailable?: string | null
  onConfirm: () => void
  onCancel: () => void
  children: ReactNode
}

// A native modal <dialog>: focus is trapped and Escape closes it. Mount it to open it, unmount it to close it.
export function ConfirmDialog({ title, confirmLabel, tone = 'primary', busy, error, unavailable = null, onConfirm, onCancel, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  // The element that had focus when the dialog opened (the button that opened it). Focus goes back there on close.
  const opener = useRef<HTMLElement | null>(null)

  useEffect(() => {
    const dialog = ref.current
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (dialog && !dialog.open) dialog.showModal()
    // Focus starts on Cancel, never on the confirm button. A reason box (textarea or input) that already has focus keeps it.
    const active = document.activeElement
    const typing = (active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement) && dialog?.contains(active)
    if (!typing) cancelRef.current?.focus()
    return () => {
      dialog?.close()
      const element = opener.current
      if (element?.isConnected) element.focus()
    }
  }, [])

  return (
    <dialog
      ref={ref}
      className="confirm"
      aria-labelledby="confirm-title"
      aria-describedby="confirm-body"
      aria-busy={busy}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onCancel()
      }}
      // Chrome can close a modal dialog without firing `cancel` (a second Escape): keep the parent state in step.
      // StrictMode's simulated unmount calls close() and the `close` event arrives after the effect re-opened the
      // dialog: only a dialog that is really closed means the user dismissed it.
      onClose={() => {
        if (!busy && !ref.current?.open) onCancel()
      }}
      onKeyDown={(event) => {
        // Enter never confirms: nothing here is a submit. A button keeps its own Enter, and the reason box takes a newline.
        if (event.key === 'Enter' && !(event.target instanceof HTMLButtonElement) && !(event.target instanceof HTMLTextAreaElement)) {
          event.preventDefault()
        }
      }}
    >
      <h2 id="confirm-title">{title}</h2>
      <div className="confirm-body" id="confirm-body">
        {children}
      </div>
      {error && (
        <p role="alert" className="error" data-testid="confirm-error">
          {error}
        </p>
      )}
      {unavailable && (
        <p role="note" className="note" data-testid="confirm-unavailable">
          {unavailable}
        </p>
      )}
      <div className="actions">
        <button ref={cancelRef} type="button" className="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" className={tone === 'danger' ? 'danger' : 'primary'} onClick={onConfirm} disabled={busy || !!unavailable}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </dialog>
  )
}
