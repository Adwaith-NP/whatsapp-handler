import { useEffect, useState } from "react";
import { getAutomationSettings, saveAutomationSettings } from "../api";

export default function AutomationPage({ onNavigate }) {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null); // {ok, text}

  useEffect(() => {
    let active = true;
    getAutomationSettings()
      .then((s) => active && setSettings(s))
      .catch((e) => active && setNote({ ok: false, text: e.message }))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  // Every change is saved immediately -- a half-applied automation rule sitting
  // behind an unclicked Save button is a bad surprise.
  async function update(changes) {
    const next = { ...settings, ...changes };
    setSettings(next);
    setBusy(true);
    setNote(null);
    try {
      const saved = await saveAutomationSettings({
        reply_to_all: next.reply_to_all,
        skip_direct: next.skip_direct,
        skip_groups: next.skip_groups,
        read_receipt_enabled: next.read_receipt_enabled,
        read_receipt_delay: next.read_receipt_delay,
        typing_delay: next.typing_delay,
        batch_window: next.batch_window,
      });
      setSettings(saved);
      setNote({ ok: true, text: "Saved." });
    } catch (err) {
      setNote({ ok: false, text: err.message });
      setSettings(settings); // roll back the optimistic change
    } finally {
      setBusy(false);
    }
  }

  // Seconds fields: type freely, save (and clamp) when the field is left.
  function typeSeconds(field, raw) {
    setSettings((s) => ({ ...s, [field]: raw }));
  }

  function commitSeconds(field, fallback) {
    const min = settings.delay_min ?? 1;
    const max = settings.delay_max ?? 60;
    const parsed = parseInt(settings[field], 10);
    const clamped = Number.isNaN(parsed) ? fallback : Math.min(max, Math.max(min, parsed));
    update({ [field]: clamped });
  }

  if (loading) {
    return (
      <section className="card">
        <h2>Automatic replies</h2>
        <p className="muted">Loading…</p>
      </section>
    );
  }

  if (!settings) {
    return (
      <section className="card">
        <h2>Automatic replies</h2>
        {note && <p className="error">{note.text}</p>}
      </section>
    );
  }

  const aiReady = settings.ai_configured;
  const on = settings.reply_to_all;

  return (
    <>
      {!aiReady && (
        <section className="card">
          <p className="badge-warn">No AI connected</p>
          <p className="muted">
            Automatic replies need a Gemini API key. Add one under Settings →
            Gemini AI, then come back here.
          </p>
          <div className="button-row">
            <button className="ghost" onClick={() => onNavigate("settings")}>
              Go to Settings
            </button>
          </div>
        </section>
      )}

      <section className={`card${aiReady ? "" : " disabled-card"}`}>
        <h2>Automatic replies</h2>

        <div className="toggle-row">
          <div>
            <div className="toggle-label">Reply to every incoming message</div>
            <p className="hint">
              When a new message arrives, the AI answers it using the
              instructions from your Gemini settings.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={on}
            aria-label="Reply to every incoming message"
            className={`switch${on ? " on" : ""}`}
            disabled={!aiReady || busy}
            onClick={() => update({ reply_to_all: !on })}
          >
            <span className="knob" />
          </button>
        </div>

        {on && (
          <div className="subsection">
            <label>Don't reply in these chats</label>
            <p className="hint">Anything ticked here is left alone.</p>

            <label className="check-row">
              <input
                type="checkbox"
                checked={settings.skip_direct}
                disabled={!aiReady || busy}
                onChange={(e) => update({ skip_direct: e.target.checked })}
              />
              <span>
                One-person chats
                <span className="hint"> — direct 1:1 conversations</span>
              </span>
            </label>

            <label className="check-row">
              <input
                type="checkbox"
                checked={settings.skip_groups}
                disabled={!aiReady || busy}
                onChange={(e) => update({ skip_groups: e.target.checked })}
              />
              <span>
                Group chats
                <span className="hint"> — every group you're in</span>
              </span>
            </label>

            {settings.skip_direct && settings.skip_groups && (
              <p className="badge-warn">
                Both types are excluded, so nothing will be answered.
              </p>
            )}
          </div>
        )}

        {on && (
          <div className="subsection">
            <label>Timing</label>
            <p className="hint">
              How long to wait before reacting, so replies don't land the instant
              a message arrives. Between {settings.delay_min ?? 1} and{" "}
              {settings.delay_max ?? 60} seconds.
            </p>

            <div className="toggle-row timing-row">
              <div>
                <div className="toggle-label">Blue ticks</div>
                <p className="hint">Mark the message as read before replying.</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={settings.read_receipt_enabled}
                aria-label="Mark messages as read"
                className={`switch${settings.read_receipt_enabled ? " on" : ""}`}
                disabled={!aiReady || busy}
                onClick={() =>
                  update({ read_receipt_enabled: !settings.read_receipt_enabled })
                }
              >
                <span className="knob" />
              </button>
            </div>

            {settings.read_receipt_enabled && (
              <div className="seconds-field">
                <label htmlFor="read-delay">Blue ticks appear after</label>
                <div className="seconds-input">
                  <input
                    id="read-delay"
                    type="number"
                    inputMode="numeric"
                    min={settings.delay_min ?? 1}
                    max={settings.delay_max ?? 60}
                    value={settings.read_receipt_delay}
                    disabled={!aiReady || busy}
                    onChange={(e) => typeSeconds("read_receipt_delay", e.target.value)}
                    onBlur={() => commitSeconds("read_receipt_delay", 5)}
                  />
                  <span className="unit">seconds</span>
                </div>
              </div>
            )}

            <div className="seconds-field">
              <label htmlFor="typing-delay">Typing starts after</label>
              <div className="seconds-input">
                <input
                  id="typing-delay"
                  type="number"
                  inputMode="numeric"
                  min={settings.delay_min ?? 1}
                  max={settings.delay_max ?? 60}
                  value={settings.typing_delay}
                  disabled={!aiReady || busy}
                  onChange={(e) => typeSeconds("typing_delay", e.target.value)}
                  onBlur={() => commitSeconds("typing_delay", 3)}
                />
                <span className="unit">seconds</span>
              </div>
              <p className="hint">
                {settings.read_receipt_enabled
                  ? "Counted from the moment the blue ticks appear."
                  : "Counted from the moment the message arrives."}{" "}
                The reply is sent as soon as the AI finishes.
              </p>
            </div>

            <div className="seconds-field">
              <label htmlFor="batch-window">Wait for follow-up messages</label>
              <div className="seconds-input">
                <input
                  id="batch-window"
                  type="number"
                  inputMode="numeric"
                  min={settings.delay_min ?? 1}
                  max={settings.delay_max ?? 60}
                  value={settings.batch_window}
                  disabled={!aiReady || busy}
                  onChange={(e) => typeSeconds("batch_window", e.target.value)}
                  onBlur={() => commitSeconds("batch_window", 6)}
                />
                <span className="unit">seconds</span>
              </div>
              <p className="hint">
                People often split one thought across several quick messages.
                They are held this long after the last one and answered together
                — and the wait keeps extending while the person is still typing.
              </p>
            </div>

            <p className="hint timeline">
              A message arriving now would be{" "}
              {settings.read_receipt_enabled
                ? `read after ${settings.read_receipt_delay}s, typing from ${
                    Number(settings.read_receipt_delay || 0) +
                    Number(settings.typing_delay || 0)
                  }s`
                : `typed from ${settings.typing_delay}s`}
              , then answered.
            </p>
          </div>
        )}

        {note && <p className={note.ok ? "muted" : "error"}>{note.text}</p>}
      </section>

      {aiReady && (
        <section className="card">
          <h2>What it will use</h2>
          <p className="muted">
            Model <strong>{settings.ai_model}</strong>.{" "}
            {settings.ai_has_instruction
              ? "Your saved instructions decide what it answers and what it declines."
              : "No instructions set — it will answer anything. Add instructions under Settings → Gemini AI to limit it."}
          </p>
        </section>
      )}
    </>
  );
}
