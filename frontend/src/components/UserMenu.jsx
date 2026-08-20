import { useEffect, useRef, useState } from "react";
import { ChevronIcon } from "./Icons.jsx";

export default function UserMenu({ user, onLogout }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);

  // Click anywhere else (or press Escape) to dismiss.
  useEffect(() => {
    if (!open) return;
    function onDown(e) {
      if (wrap.current && !wrap.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const name = user?.display_name || user?.username || "";
  const initial = (name.trim()[0] || "?").toUpperCase();

  return (
    <div className="user-menu" ref={wrap}>
      <button
        type="button"
        className="user-chip"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={name ? `Account: ${name}` : "Account"}
      >
        <span className="avatar" aria-hidden="true">
          {initial}
        </span>
        <span className="user-name">{name || "…"}</span>
        <ChevronIcon />
      </button>

      {open && (
        <div className="user-dropdown" role="menu">
          <div className="user-dropdown-head">
            <span className="avatar" aria-hidden="true">
              {initial}
            </span>
            <div>
              <div className="user-name-full">{name}</div>
              <div className="hint">Signed in</div>
            </div>
          </div>
          <button type="button" className="dropdown-item" role="menuitem" onClick={onLogout}>
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
