"use client";
import { useEffect, useRef, useState } from "react";

export default function CollectionInput({ value, defaultValue = "", onChange, disabled, ...props }) {
  const controlled = value !== undefined;
  const [localValue, setLocalValue] = useState(defaultValue);
  const [editing, setEditing] = useState(false);
  const input = useRef(null);
  const text = String(controlled ? value ?? "" : localValue);
  const tagged = Boolean(text) && !editing;
  useEffect(() => {
    const form = input.current?.form;
    const reset = () => { if (!controlled) setLocalValue(defaultValue); setEditing(false); };
    form?.addEventListener("reset", reset);
    return () => form?.removeEventListener("reset", reset);
  }, [controlled, defaultValue]);
  function change(event) {
    if (!controlled) setLocalValue(event.target.value);
    onChange?.(event);
  }
  function clear() {
    // Dispatch the same input change used by the surrounding controlled form.
    const field = input.current;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(field, "");
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.focus();
  }
  return <div className={`collection-tag-input${tagged ? " has-tag" : ""}`}>
    <div className="collection-tag-value">
      <input {...props} ref={input} disabled={disabled} value={text} onChange={change}
        style={tagged ? { width: `${Math.max(4, text.length + 1)}ch` } : undefined}
        onFocus={() => setEditing(true)} onBlur={() => setEditing(false)}
        onKeyDown={event => {
          if ((event.key === "Enter" || event.key === " ") && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (text) event.currentTarget.blur();
          }
        }} />
      {tagged && <button type="button" className="collection-tag-remove" disabled={disabled} aria-label={`Remove collection ${text}`} onClick={clear}>×</button>}
    </div>
  </div>;
}
