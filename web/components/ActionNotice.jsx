"use client";
import {useEffect, useId, useRef} from "react";
import {createPortal} from "react-dom";

export default function ActionNotice({message, onClose}) {
  const dialog = useRef(null);
  const title = useId();
  const description = useId();
  useEffect(() => {
    if (!message || !dialog.current) return;
    const previous = document.activeElement;
    const current = dialog.current;
    if (!current.open) current.showModal();
    return () => {
      current.close();
      if (previous?.isConnected) previous.focus?.();
    };
  }, [message]);
  if (!message || typeof document === "undefined") return null;
  return createPortal(<dialog ref={dialog} className="action-notice" aria-labelledby={title} aria-describedby={description}
    onCancel={e => {e.preventDefault(); onClose();}}>
    <div className="action-notice-heading"><span aria-hidden="true" className="action-notice-icon">!</span><button type="button" className="action-notice-close" aria-label="Close message" onClick={onClose}>×</button></div>
    <h2 id={title}>Couldn’t complete that</h2>
    <p id={description}>{typeof message === "string" ? message : "Something went wrong. Please try again."}</p>
    <button type="button" className="action-notice-dismiss" autoFocus onClick={onClose}>Got it</button>
  </dialog>, document.body);
}
