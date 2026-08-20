import { useState } from "react";

// navigator.clipboard only exists in a secure context (https, or localhost).
// Served over plain http on a server IP it is undefined, so fall back to the
// old execCommand trick before giving up.
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through */
  }
  try {
    const el = document.createElement("textarea");
    el.value = text;
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  } catch {
    return false;
  }
}

export default function CodeBlock({ label, code }) {
  const [state, setState] = useState("");

  async function copy() {
    const ok = await copyText(code);
    setState(ok ? "Copied" : "Press ⌘/Ctrl+C");
    setTimeout(() => setState(""), 2000);
  }

  return (
    <div className="code-wrap">
      <div className="code-head">
        <span className="code-label">{label}</span>
        <button type="button" className="link-button" onClick={copy}>
          {state || "Copy"}
        </button>
      </div>
      <pre className="code-block">{code}</pre>
    </div>
  );
}

export { copyText };
