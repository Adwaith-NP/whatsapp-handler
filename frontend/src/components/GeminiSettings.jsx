import { useEffect, useState } from "react";
import { getGeminiSettings, saveGeminiSettings, testGemini } from "../api";

const PLACEHOLDER_INSTRUCTION =
  "e.g. You answer questions about our bakery only: opening hours, menu, and " +
  "order status. If a message is about anything else, politely say you can " +
  "only help with bakery questions.";

export default function GeminiSettings() {
  const [saved, setSaved] = useState(null); // what the server has stored
  const [apiKey, setApiKey] = useState(""); // only ever holds a NEW key
  const [model, setModel] = useState("");
  const [instruction, setInstruction] = useState("");
  const [testMessage, setTestMessage] = useState("Hi, what can you help me with?");

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState(null); // {ok, text}
  const [reply, setReply] = useState("");

  useEffect(() => {
    let active = true;
    getGeminiSettings()
      .then((s) => {
        if (!active) return;
        setSaved(s);
        setModel(s.model || s.default_model || "");
        setInstruction(s.instruction || "");
      })
      .catch((e) => active && setNote({ ok: false, text: e.message }))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  async function save(e) {
    e.preventDefault();
    setBusy("save");
    setNote(null);
    try {
      // A blank key means "keep the stored one" — we never received it to resend.
      const s = await saveGeminiSettings({ model, instruction, api_key: apiKey });
      setSaved(s);
      setApiKey("");
      setNote({ ok: true, text: "Settings saved." });
    } catch (err) {
      setNote({ ok: false, text: err.message });
    } finally {
      setBusy("");
    }
  }

  async function runTest() {
    setBusy("test");
    setNote(null);
    setReply("");
    try {
      // Tests what's currently in the form, so you can try an instruction
      // before committing it.
      const r = await testGemini({ model, instruction, api_key: apiKey, message: testMessage });
      setReply(r.reply);
      setNote({ ok: true, text: `Gemini replied (${r.model}).` });
    } catch (err) {
      setNote({ ok: false, text: err.message });
    } finally {
      setBusy("");
    }
  }

  async function removeKey() {
    setBusy("clear");
    setNote(null);
    try {
      const s = await saveGeminiSettings({ model, instruction, clear_api_key: true });
      setSaved(s);
      setApiKey("");
      setNote({ ok: true, text: "API key removed." });
    } catch (err) {
      setNote({ ok: false, text: err.message });
    } finally {
      setBusy("");
    }
  }

  if (loading) {
    return (
      <section className="card">
        <h2>Gemini AI</h2>
        <p className="muted">Loading…</p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>Gemini AI</h2>
      <p className="muted">
        Connect a Gemini API key and set the rules the AI must follow. Nothing
        replies automatically yet — this is the configuration, and the test
        button below lets you check the key and try out your instructions.
      </p>

      <form onSubmit={save}>
        <label>API key</label>
        <input
          type="password"
          autoComplete="off"
          placeholder={
            saved?.has_api_key ? `Stored key ${saved.api_key_hint} — type to replace` : "AIza…"
          }
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        <p className="hint">
          Get one from Google AI Studio. It's stored on your server and never sent
          back to this page.
        </p>

        <label>Model</label>
        <input
          placeholder={saved?.default_model || "gemini-3.6-flash"}
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />

        <label>Instructions — what the AI is allowed to answer</label>
        <textarea
          rows={6}
          placeholder={PLACEHOLDER_INSTRUCTION}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
        />
        <p className="hint">
          Be specific about the topics it should handle and what to say when a
          message falls outside them.
        </p>

        <button className="primary" disabled={!!busy}>
          {busy === "save" ? "Saving…" : "Save settings"}
        </button>
      </form>

      <div className="divider" />

      <label>Test message</label>
      <input
        placeholder="Ask something the AI should — or shouldn't — answer"
        value={testMessage}
        onChange={(e) => setTestMessage(e.target.value)}
      />
      <div className="button-row">
        <button className="ghost" onClick={runTest} disabled={!!busy}>
          {busy === "test" ? "Testing…" : "Test with Gemini"}
        </button>
        {saved?.has_api_key && (
          <button className="ghost" onClick={removeKey} disabled={!!busy}>
            {busy === "clear" ? "Removing…" : "Remove key"}
          </button>
        )}
      </div>

      {note && <p className={note.ok ? "badge-ok" : "error"}>{note.text}</p>}
      {reply && <pre className="reply-box">{reply}</pre>}
    </section>
  );
}
