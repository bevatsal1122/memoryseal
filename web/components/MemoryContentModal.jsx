"use client";

import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

export default function MemoryContentModal({ onClose, title: heading, namespace, children }) {
  const dialog = useRef(null);
  const title = useId();
  useEffect(() => {
    if (!dialog.current) return;
    const previous = document.activeElement;
    const current = dialog.current;
    current.showModal();
    return () => {
      current.close();
      if (previous?.isConnected) previous.focus?.();
    };
  }, []);

  if (typeof document === "undefined") return null;
  return createPortal(
    <dialog ref={dialog} className="saved-memory-modal memory-reader-modal" aria-labelledby={title}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === event.currentTarget) {
        const box = event.currentTarget.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose();
      } }}>
      <header>
        <div><span className="saved-memory-eyebrow">{namespace}</span><h2 id={title}>{heading}</h2></div>
        <button type="button" className="saved-memory-close" aria-label="Close memory" autoFocus onClick={onClose}>×</button>
      </header>
      <div className="saved-memory-body">
        {children}
      </div>
    </dialog>, document.body,
  );
}
