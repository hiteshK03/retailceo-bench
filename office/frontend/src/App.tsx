import { useEffect, useMemo, useRef, useState } from "react";
import { createRun, openRunStream } from "./lib/api";
import type { OfficeEvent, RunConfig, WeekPayload } from "./types";
import { EventLog } from "./components/EventLog";
import { JournalPanel } from "./components/JournalPanel";
import { KpiHud } from "./components/KpiHud";
import { OfficeCanvas } from "./components/OfficeCanvas";
import { ProposalPanel } from "./components/ProposalPanel";
import { RunControls } from "./components/RunControls";
import "./styles/app.css";

const DEFAULT_CONFIG: RunConfig = {
  seed: 42,
  policy: "heuristic",
  difficulty: "medium",
  weeks: 12,
};

export function App() {
  const [config, setConfig] = useState<RunConfig>(DEFAULT_CONFIG);
  const [events, setEvents] = useState<OfficeEvent[]>([]);
  const [status, setStatus] = useState("idle");
  const [statusMessage, setStatusMessage] = useState("Waiting for the CEO.");
  const [maxWeeks, setMaxWeeks] = useState(12);
  const [currentWeek, setCurrentWeek] = useState<WeekPayload | undefined>();
  const [summary, setSummary] = useState<Record<string, unknown> | undefined>();
  const [playbackDelayMs, setPlaybackDelayMs] = useState(750);
  const [manualReview, setManualReview] = useState(true);
  const [queuedEventsCount, setQueuedEventsCount] = useState(0);
  const socketRef = useRef<WebSocket | null>(null);
  const eventQueueRef = useRef<OfficeEvent[]>([]);
  const playbackTimerRef = useRef<number | null>(null);
  const playbackDelayRef = useRef(playbackDelayMs);
  const manualReviewRef = useRef(manualReview);

  const running = status === "created" || status === "running";
  const journal = currentWeek?.journal;
  const journalDecisionKpi = currentWeek?.decision_kpi ?? currentWeek?.kpi;
  const headline = useMemo(() => {
    if (!summary) return "Live department inbox, CEO decisions, and weekly KPI movement.";
    const nested = summary.summary as Record<string, unknown> | undefined;
    const total = typeof nested?.total_reward === "number" ? nested.total_reward.toFixed(3) : "-";
    return `Run complete. Total reward ${total}.`;
  }, [summary]);

  useEffect(() => {
    playbackDelayRef.current = playbackDelayMs;
  }, [playbackDelayMs]);

  useEffect(() => {
    manualReviewRef.current = manualReview;
    if (manualReview && playbackTimerRef.current !== null) {
      window.clearTimeout(playbackTimerRef.current);
      playbackTimerRef.current = null;
    }
    if (!manualReview) {
      scheduleNextEvent();
    }
  }, [manualReview]);

  async function startRun() {
    stopRun();
    clearPlaybackQueue();
    setEvents([]);
    setCurrentWeek(undefined);
    setSummary(undefined);
    setStatus("created");
    setStatusMessage("Creating live run...");
    const run = await createRun(config);
    const socket = openRunStream(run.run_id, queueEvent);
    socketRef.current = socket;
  }

  function stopRun() {
    socketRef.current?.close();
    socketRef.current = null;
    clearPlaybackQueue();
    setStatus((prev) => (prev === "running" || prev === "created" ? "stopped" : prev));
  }

  function clearPlaybackQueue() {
    eventQueueRef.current = [];
    setQueuedEventsCount(0);
    if (playbackTimerRef.current !== null) {
      window.clearTimeout(playbackTimerRef.current);
      playbackTimerRef.current = null;
    }
  }

  function queueEvent(event: OfficeEvent) {
    if (event.type === "run_started" || event.type === "run_failed") {
      applyEvent(event);
      return;
    }
    if (manualReviewRef.current) {
      eventQueueRef.current.push(event);
      setQueuedEventsCount(eventQueueRef.current.length);
      return;
    }
    if (playbackDelayRef.current <= 0) {
      applyEvent(event);
      return;
    }
    eventQueueRef.current.push(event);
    setQueuedEventsCount(eventQueueRef.current.length);
    scheduleNextEvent();
  }

  function scheduleNextEvent() {
    if (manualReviewRef.current) return;
    if (playbackTimerRef.current !== null || eventQueueRef.current.length === 0) return;
    const next = eventQueueRef.current[0];
    const delay = next.type === "run_started" ? 0 : playbackDelayRef.current;
    playbackTimerRef.current = window.setTimeout(() => {
      playbackTimerRef.current = null;
      const event = eventQueueRef.current.shift();
      setQueuedEventsCount(eventQueueRef.current.length);
      if (event) applyEvent(event);
      scheduleNextEvent();
    }, delay);
  }

  function nextQueuedEvent() {
    if (playbackTimerRef.current !== null) {
      window.clearTimeout(playbackTimerRef.current);
      playbackTimerRef.current = null;
    }
    const event = eventQueueRef.current.shift();
    setQueuedEventsCount(eventQueueRef.current.length);
    if (event) applyEvent(event);
  }

  function applyEvent(event: OfficeEvent) {
    setEvents((prev) => [...prev.slice(-39), event]);
    if (event.type === "run_started") {
      setStatus("running");
      setStatusMessage("CEO office online.");
      const nextMaxWeeks = event.payload.max_weeks;
      if (typeof nextMaxWeeks === "number") setMaxWeeks(nextMaxWeeks);
    }
    if (event.type === "week_started") {
      setStatusMessage(`Week ${(event.payload as WeekPayload).week}: departments are filing proposals.`);
      setCurrentWeek(event.payload as unknown as WeekPayload);
    }
    if (event.type === "agent_thinking") {
      setStatusMessage("CEO is reviewing the inbox.");
    }
    if (event.type === "agent_called") {
      const wall = event.payload.wall_s;
      const suffix = typeof wall === "number" ? ` (${wall.toFixed(1)}s)` : "";
      setStatusMessage(`CEO decision complete${suffix}.`);
    }
    if (event.type === "week_completed") {
      setCurrentWeek(event.payload as unknown as WeekPayload);
      setStatusMessage(`Week ${(event.payload as WeekPayload).week} closed. Journal posted.`);
    }
    if (event.type === "run_completed") {
      setStatus("completed");
      setSummary(event.payload);
      setStatusMessage("Quarter complete.");
      socketRef.current?.close();
      socketRef.current = null;
    }
    if (event.type === "run_failed") {
      setStatus("failed");
      setStatusMessage(String(event.payload.message ?? "Run failed."));
    }
  }

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">Retail CEO Pixel Office</p>
          <h1>Live CEO Command Floor</h1>
          <p>{headline}</p>
        </div>
      </header>

      <section className="dashboard-grid">
        <div className="left-rail">
          <JournalPanel
            journal={journal}
            statusMessage={statusMessage}
            decisionKpi={journalDecisionKpi}
          />
          <ProposalPanel week={currentWeek} />
        </div>
        <div className="office-stage">
          <OfficeCanvas week={currentWeek} statusMessage={statusMessage} />
        </div>
        <div className="right-rail">
          <RunControls
            config={config}
            running={running}
            playbackDelayMs={playbackDelayMs}
            manualReview={manualReview}
            queuedEventsCount={queuedEventsCount}
            onChange={setConfig}
            onPlaybackDelayChange={setPlaybackDelayMs}
            onManualReviewChange={setManualReview}
            onNextEvent={nextQueuedEvent}
            onStart={startRun}
            onStop={stopRun}
          />
          <KpiHud week={currentWeek} maxWeeks={maxWeeks} status={status} />
          <EventLog events={events} />
        </div>
      </section>
    </main>
  );
}

