import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, ErrorLine } from "../ui";

// Native <dialog>, so focus trapping and Esc come for free.
export function Confirm({
  open,
  title,
  children,
  confirmLabel,
  danger,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => Promise<unknown>;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setError(null);
      dialog.showModal();
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] border border-ink bg-paper p-0 text-ink backdrop:bg-ink/40"
    >
      <div className="border-b border-ink px-5 py-3 font-semibold">{title}</div>
      <div className="space-y-3 px-5 py-4 text-sm">{children}</div>
      <div className="px-5">
        <ErrorLine error={error} />
      </div>
      <div className="flex justify-end gap-2 border-t border-rule px-5 py-3">
        <Button type="button" onClick={onClose} disabled={busy}>
          cancel
        </Button>
        <Button type="button" tone={danger ? "danger" : "solid"} onClick={go} disabled={busy}>
          {busy ? "…" : confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
