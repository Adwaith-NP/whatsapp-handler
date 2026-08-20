import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { getStatus } from "../api";

const POLL_MS = 2500;
// The worker restarts itself when the device is unlinked, so its API is briefly
// unreachable. Don't surface an error until it stays down.
const FAILURES_BEFORE_ERROR = 4;

// Older worker builds only returned {connected, qr, jid}; derive a state from
// those so the portal keeps working if the two are ever out of sync.
function stateOf(status) {
  if (!status) return null;
  if (status.state) return status.state;
  if (status.connected) return "connected";
  return status.qr ? "awaiting_scan" : "starting";
}

export default function Connect() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [restarting, setRestarting] = useState(false);
  const failures = useRef(0);

  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const s = await getStatus();
        if (!active) return;
        failures.current = 0;
        setStatus(s);
        setError("");
        setRestarting(false);
      } catch (e) {
        if (!active) return;
        failures.current += 1;
        const down = failures.current >= FAILURES_BEFORE_ERROR;
        setError(down ? e.message : "");
        setRestarting(!down);
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS); // refresh so a rotated QR stays current
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const state = stateOf(status);

  return (
    <section className="card">
      <h2>Account connection</h2>
      {error && <p className="error">{error}</p>}
      {!status && !error && <p className="muted">Loading…</p>}

      {state === "connected" && (
        <p className="badge-ok">
          Connected{status.jid ? ` as +${status.jid}` : ""}
        </p>
      )}

      {state === "awaiting_scan" && status.qr && (
        <div className="qr-box">
          <p>
            Open WhatsApp on your phone → <strong>Linked devices</strong> →{" "}
            <strong>Link a device</strong>, then scan:
          </p>
          <div className="qr-frame">
            <QRCodeSVG value={status.qr} size={256} />
          </div>
          <p className="muted">The code refreshes automatically until you scan it.</p>
        </div>
      )}

      {state === "logged_out" && (
        <>
          <p className="badge-warn">Device unlinked from WhatsApp</p>
          <p className="muted">
            This portal was removed from your phone's linked devices. Generating a
            new QR code — it appears here in a few seconds.
          </p>
        </>
      )}

      {state === "reconnecting" && (
        <>
          <p className="badge-warn">Connection lost — reconnecting…</p>
          <p className="muted">
            Still linked to +{status.jid || "your account"}. Messages can't be sent
            until the connection is back.
          </p>
        </>
      )}

      {(state === "starting" || (state === "awaiting_scan" && !status.qr)) && (
        <p className="muted">Waiting for the WhatsApp worker to produce a QR code…</p>
      )}

      {restarting && (
        <p className="muted">Reconnecting to the WhatsApp worker…</p>
      )}
    </section>
  );
}
