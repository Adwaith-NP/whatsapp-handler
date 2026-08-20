import { useState } from "react";
import { login, setToken } from "../api";
import { WhatsAppLogo } from "./Icons.jsx";

export default function Login({ onLogin, product = "WhatsApp Handler" }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const { token } = await login(username, password);
      setToken(token);
      onLogin();
    } catch (_e) {
      setErr("Invalid username or password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="card login-card" onSubmit={submit}>
        <span className="product-mark login-mark">
          <WhatsAppLogo size={32} />
        </span>
        <h1>{product}</h1>
        <p className="muted">Sign in to manage your connection</p>
        <input
          name="username"
          placeholder="Username"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck="false"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <input
          name="password"
          placeholder="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button className="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {err && <p className="error">{err}</p>}
      </form>
    </div>
  );
}
