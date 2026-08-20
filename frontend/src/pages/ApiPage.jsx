import { useEffect, useState } from "react";
import { listApiKeys, createApiKey, deleteApiKey } from "../api";
import CodeBlock, { copyText } from "../components/CodeBlock.jsx";

const KEY_TYPES = [
  {
    id: "send_message",
    label: "Send a message",
    blurb: "Send a WhatsApp message to a phone number with the text you provide.",
  },
];

const ENDPOINT_PATH = "/api/v1/messages/";

function snippets(baseUrl, keyPlaceholder) {
  const url = `${baseUrl}${ENDPOINT_PATH}`;
  return {
    curl: `curl -X POST "${url}" \\
  -H "X-API-Key: ${keyPlaceholder}" \\
  -H "Content-Type: application/json" \\
  -d '{"phone": "971568854459", "message": "Hello from the API"}'`,

    python: `import requests

response = requests.post(
    "${url}",
    headers={"X-API-Key": "${keyPlaceholder}"},
    json={
        "phone": "971568854459",   # country code + number, digits only
        "message": "Hello from the API",
    },
    timeout=30,
)

print(response.status_code, response.json())
# 200 {'ok': True, 'phone': '971568854459'}`,

    javascript: `const response = await fetch("${url}", {
  method: "POST",
  headers: {
    "X-API-Key": "${keyPlaceholder}",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    phone: "971568854459",   // country code + number, digits only
    message: "Hello from the API",
  }),
});

const data = await response.json();
console.log(response.status, data);
// 200 { ok: true, phone: '971568854459' }`,
  };
}

function Details({ baseUrl }) {
  const code = snippets(baseUrl, "YOUR_API_KEY");
  return (
    <div className="details-body">
      <h3>Endpoint</h3>
      <p className="muted mono">POST {baseUrl}{ENDPOINT_PATH}</p>

      <h3>Authentication</h3>
      <p className="muted">
        Send your key in the <code>X-API-Key</code> header.{" "}
        <code>Authorization: Bearer &lt;key&gt;</code> works too.
      </p>

      <h3>Request body</h3>
      <table className="spec-table">
        <tbody>
          <tr>
            <td className="mono">phone</td>
            <td>
              string, required — country code + number, digits only. A leading{" "}
              <code>+</code> and spaces are stripped for you.
            </td>
          </tr>
          <tr>
            <td className="mono">message</td>
            <td>string, required — the text to send.</td>
          </tr>
        </tbody>
      </table>

      <h3>Responses</h3>
      <table className="spec-table">
        <tbody>
          <tr>
            <td className="mono">200</td>
            <td>
              <code>{`{"ok": true, "phone": "971568854459"}`}</code>
            </td>
          </tr>
          <tr>
            <td className="mono">400</td>
            <td>Missing or malformed phone/message.</td>
          </tr>
          <tr>
            <td className="mono">401</td>
            <td>Missing, unknown, or revoked API key.</td>
          </tr>
          <tr>
            <td className="mono">503</td>
            <td>WhatsApp is not connected — scan the QR under Settings.</td>
          </tr>
          <tr>
            <td className="mono">502</td>
            <td>The message could not be delivered; the reason is in the body.</td>
          </tr>
        </tbody>
      </table>

      <h3>Examples</h3>
      <CodeBlock label="Python" code={code.python} />
      <CodeBlock label="JavaScript" code={code.javascript} />
      <CodeBlock label="curl" code={code.curl} />
    </div>
  );
}

export default function ApiPage() {
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [type, setType] = useState(KEY_TYPES[0].id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fresh, setFresh] = useState(null); // the just-created key, shown once
  const [copied, setCopied] = useState("");
  const [openDetails, setOpenDetails] = useState(false);

  const baseUrl = window.location.origin;

  useEffect(() => {
    let active = true;
    listApiKeys()
      .then((k) => active && setKeys(k))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await createApiKey(name.trim(), type);
      setFresh(created);
      setKeys((prev) => [created, ...prev]);
      setName("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(row) {
    if (!window.confirm(`Delete "${row.name}"? Any app using it stops working immediately.`)) {
      return;
    }
    setError("");
    try {
      await deleteApiKey(row.id);
      setKeys((prev) => prev.filter((k) => k.id !== row.id));
      if (fresh?.id === row.id) setFresh(null);
    } catch (err) {
      setError(err.message);
    }
  }

  async function copyKey() {
    const ok = await copyText(fresh.key);
    setCopied(ok ? "Copied" : "Press ⌘/Ctrl+C");
    setTimeout(() => setCopied(""), 2000);
  }

  const activeType = KEY_TYPES.find((t) => t.id === type) || KEY_TYPES[0];

  return (
    <>
      <section className="card">
        <h2>Create an API key</h2>
        <p className="muted">
          Give another application permission to use this portal. The key is
          shown once, when you create it.
        </p>

        <form onSubmit={create}>
          <label>Name</label>
          <input
            placeholder="e.g. Website contact form"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />

          <label>Type</label>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {KEY_TYPES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
          <p className="hint">{activeType.blurb}</p>

          <button className="primary" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create API key"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}
      </section>

      {fresh?.key && (
        <section className="card key-reveal">
          <h2>Your new key: {fresh.name}</h2>
          <p className="badge-warn">Copy it now — it is not shown again</p>
          <div className="key-value">
            <code>{fresh.key}</code>
            <button type="button" className="ghost" onClick={copyKey}>
              {copied || "Copy"}
            </button>
          </div>
          <p className="hint">
            Only a hash is stored, so nobody — including this portal — can show
            it to you later. Lose it and you create a new one.
          </p>
        </section>
      )}

      <section className="card">
        <h2>Keys</h2>
        {loading && <p className="muted">Loading…</p>}
        {!loading && keys.length === 0 && (
          <p className="muted">No API keys yet.</p>
        )}

        {keys.map((k) => (
          <div key={k.id} className="key-row">
            <div>
              <div className="key-name">{k.name}</div>
              <div className="key-meta">
                <span className="mono">{k.prefix}…</span> · {k.type_label} ·
                created {new Date(k.created_at).toLocaleDateString()} ·{" "}
                {k.last_used_at
                  ? `last used ${new Date(k.last_used_at).toLocaleString()}`
                  : "never used"}
              </div>
            </div>
            <button type="button" className="ghost danger" onClick={() => revoke(k)}>
              Delete
            </button>
          </div>
        ))}
      </section>

      <section className="card">
        <div className="details-head">
          <h2>Using the API</h2>
          <button
            type="button"
            className="link-button"
            onClick={() => setOpenDetails((v) => !v)}
          >
            {openDetails ? "Hide details" : "Show more details"}
          </button>
        </div>
        <p className="muted">
          One request sends one WhatsApp message from the connected account.
        </p>
        {openDetails && <Details baseUrl={baseUrl} />}
      </section>
    </>
  );
}
