import { useEffect, useRef, useState } from "react";
import { getQueue } from "../api";

const POLL_MS = 1200;
const FAILURES_BEFORE_ERROR = 4;

// The life of a reply, in order. The active one lights up.
const STAGES = [
  { id: "collecting", label: "Collecting", hint: "waiting for more messages" },
  { id: "reading", label: "Reading", hint: "before the blue ticks" },
  { id: "waiting", label: "Pausing", hint: "before typing starts" },
  { id: "thinking", label: "Thinking", hint: "asking the AI" },
  { id: "sending", label: "Sending", hint: "delivering the reply" },
];

function initials(name) {
  const clean = (name || "?").trim();
  return (clean[0] || "?").toUpperCase();
}

function secs(n) {
  if (n === null || n === undefined) return "";
  return n < 60 ? `${Math.round(n)}s` : `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`;
}

function Avatar({ name, isGroup, tone = "" }) {
  return (
    <span className={`q-avatar ${tone}`} aria-hidden="true">
      {isGroup ? "#" : initials(name)}
    </span>
  );
}

function StageTrack({ stage }) {
  const activeIndex = STAGES.findIndex((s) => s.id === stage);
  return (
    <ol className="stage-track">
      {STAGES.map((s, i) => {
        const state = i < activeIndex ? "done" : i === activeIndex ? "active" : "todo";
        return (
          <li key={s.id} className={`stage ${state}`}>
            <span className="stage-dot" />
            <span className="stage-label">{s.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export default function QueuePage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const failures = useRef(0);

  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const q = await getQueue();
        if (!active) return;
        failures.current = 0;
        setData(q);
        setError("");
      } catch (e) {
        if (!active) return;
        failures.current += 1;
        if (failures.current >= FAILURES_BEFORE_ERROR) setError(e.message);
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  if (!data && !error) {
    return (
      <section className="card">
        <h2>Reply queue</h2>
        <p className="muted">Loading…</p>
      </section>
    );
  }

  const current = data?.current;
  const waiting = data?.waiting || [];
  const recent = data?.recent || [];
  const activeStage = STAGES.find((s) => s.id === current?.stage);

  return (
    <>
      {error && (
        <section className="card">
          <p className="error">{error}</p>
        </section>
      )}

      <section className="card">
        <div className="q-head">
          <h2>Now replying</h2>
          <span className={`q-pill ${current ? "live" : ""}`}>
            {current ? "Active" : "Idle"}
          </span>
        </div>

        {!current && (
          <p className="muted">
            Nobody is being answered right now. New messages appear here the
            moment they arrive.
          </p>
        )}

        {current && (
          <>
            <div className="q-person">
              <Avatar name={current.name} isGroup={current.is_group} tone="accent" />
              <div className="q-person-body">
                <div className="q-name">
                  {current.name}
                  {current.is_group && <span className="q-tag">group</span>}
                </div>
                <div className="q-meta">
                  {current.messages} message{current.messages === 1 ? "" : "s"} ·
                  waiting {secs(current.waiting_for)}
                </div>
              </div>
            </div>

            {current.preview && <p className="q-preview">{current.preview}</p>}

            <StageTrack stage={current.stage} />
            {activeStage && <p className="hint">{activeStage.hint}</p>}
          </>
        )}
      </section>

      <section className="card">
        <div className="q-head">
          <h2>Waiting next</h2>
          <span className="q-pill">{waiting.length} in queue</span>
        </div>

        {waiting.length === 0 && (
          <p className="muted">Queue is empty — everyone has been answered.</p>
        )}

        {waiting.length > 0 && (
          <ol className="q-list">
            {waiting.map((item) => (
              <li key={item.chat} className="q-item">
                <span className="q-position">{item.position}</span>
                <Avatar name={item.name} isGroup={item.is_group} />
                <div className="q-person-body">
                  <div className="q-name">
                    {item.name}
                    {item.is_group && <span className="q-tag">group</span>}
                  </div>
                  <div className="q-meta">
                    {item.messages} message{item.messages === 1 ? "" : "s"} ·
                    waiting {secs(item.waiting_for)}
                    {item.ready_in > 0 && (
                      <span className="q-collecting">
                        {" "}· still collecting, {secs(item.ready_in)} left
                      </span>
                    )}
                  </div>
                  {item.preview && <div className="q-preview small">{item.preview}</div>}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {recent.length > 0 && (
        <section className="card">
          <h2>Just answered</h2>
          <ul className="q-list">
            {recent.map((item, i) => (
              <li key={`${item.chat}-${i}`} className="q-item done-item">
                <Avatar
                  name={item.name}
                  isGroup={item.is_group}
                  tone={item.outcome === "failed" ? "bad" : "muted"}
                />
                <div className="q-person-body">
                  <div className="q-name">{item.name}</div>
                  <div className="q-meta">
                    {item.outcome === "failed" ? (
                      <span className="q-failed">Failed — {item.error}</span>
                    ) : (
                      <>
                        Replied to {item.messages} message
                        {item.messages === 1 ? "" : "s"}
                        {item.took !== null && ` in ${secs(item.took)}`}
                      </>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>How the queue works</h2>
        <p className="muted">
          One person is answered at a time, in the order their messages arrived —
          nothing is dropped while a reply is in progress.
        </p>
        <p className="muted">
          When someone sends several messages in a row, they are held briefly and
          answered together as one thought rather than line by line. The wait
          extends while they are still typing, so a split message is never
          answered halfway. Adjust that window under{" "}
          <strong>Automation → Timing → Wait for follow-up messages</strong>.
        </p>
      </section>
    </>
  );
}
