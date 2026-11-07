"use client";

import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

export default function SavedMemoryModal({ open, onClose, written, children }) {
  const dialog = useRef(null);
  const title = useId();
  useEffect(() => {
    if (!open || !dialog.current) return;
    const previous = document.activeElement;
    const current = dialog.current;
    current.showModal();
    return () => {
      current.close();
      if (previous?.isConnected) previous.focus?.();
    };
  }, [open]);

  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <dialog ref={dialog} className="saved-memory-modal" aria-labelledby={title}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === event.currentTarget) {
        const box = event.currentTarget.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose();
      } }}>
      <header>
        <div><span className="saved-memory-eyebrow">MEMORY SAVED</span><h2 id={title}>{written.status === "accepted" ? "Memory saved" : "Needs owner review"}</h2></div>
        <button type="button" className="saved-memory-close" aria-label="Close saved memory" autoFocus onClick={onClose}>×</button>
      </header>
      <div className="saved-memory-body">
        <dl><div><dt>Memory ID</dt><dd><code>{written.id}</code></dd></div><div><dt>Readable at write time</dt><dd>{written.lineage_eligible ? "Yes" : "No"}</dd></div></dl>
        <section className="saved-memory-proof">{children}</section>
      </div>
    </dialog>, document.body,
  );
}
