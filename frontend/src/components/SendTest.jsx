import { useState } from "react";
import { sendMessage } from "../api";

export default function SendTest() {
  const [phone, setPhone] = useState("");
  const [message, setMessage] = useState("Hello from my WhatsApp portal 👋");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setResult(null);
    setBusy(true);
    try {
      await sendMessage(phone, message);
      setResult({ ok: true, text: "Message sent." });
    } catch (e) {
      setResult({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Send a test message</h2>
      <form onSubmit={submit}>
        <label>Phone number (country code + number, digits only)</label>
        <input
          type="tel"
          inputMode="numeric"
          autoComplete="tel"
          placeholder="14155551234"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
        <label>Message</label>
        <textarea
          rows={3}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <button className="primary" disabled={busy}>
          {busy ? "Sending…" : "Send test message"}
        </button>
      </form>
      {result && <p className={result.ok ? "badge-ok" : "error"}>{result.text}</p>}
    </section>
  );
}
