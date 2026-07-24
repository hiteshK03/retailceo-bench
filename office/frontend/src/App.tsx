import { useEffect, useMemo, useRef, useState } from "react";
import { createRun, openRunStream, openHumanPlay, sendDecisions } from "./lib/api";
import type { Difficulty, OfficeEvent, RunConfig, WeekPayload } from "./types";
import type { PendingVerdict } from "./components/ProposalPanel";
import { allDecided, buildDecisions } from "./lib/humanPlay";
import { EventLog } from "./components/EventLog";
import { JournalPanel } from "./components/JournalPanel";
import { KpiHud } from "./components/KpiHud";
import { OfficeCanvas } from "./components/OfficeCanvas";
import { ProposalPanel } from "./components/ProposalPanel";
import { RunControls } from "./components/RunControls";
import { TopKpiBar } from "./components/TopKpiBar";
import "./styles/app.css";

const DEFAULT_CONFIG: RunConfig = {
  seed: 42,
  policy: "heuristic",
  difficulty: "medium",
  weeks: 12,
};

// Static per-difficulty baseline reward averages (from results/baselines_full.json,
// corrected reward). Shown on the human end screen for comparison.
const BASELINE_REWARDS: Record<Difficulty, { heuristic: number; oracle: number }> = {
  easy: { heuristic: 2.01, oracle: 2.01 },
  medium: { heuristic: 1.6, oracle: 1.6 },
  hard: { heuristic: 0.24, oracle: 0.32 },
};


export function App() {
  const [config, setConfig] = useState<RunConfig>(DEFAULT_CONFIG);
  const [events, setEvents] = useState<OfficeEvent[]>([]);
  const [status, setStatus] = useState("idle");
  const [statusMessage, setStatusMessage] = useState("Waiting for the CEO.");
  const [maxWeeks, setMaxWeeks] = useState(12);
  const [currentWeek, setCurrentWeek] = useState<WeekPayload | undefined>();
  const [cumulativeReward, setCumulativeReward] = useState(0);
  const [summary, setSummary] = useState<Record<string, unknown> | undefined>();
  const [playbackDelayMs, setPlaybackDelayMs] = useState(750);
  const [manualReview, setManualReview] = useState(true);
  const [queuedEventsCount, setQueuedEventsCount] = useState(0);
  const socketRef = useRef<WebSocket | null>(null);
  const eventQueueRef = useRef<OfficeEvent[]>([]);
  const playbackTimerRef = useRef<number | null>(null);
  const playbackDelayRef = useRef(playbackDelayMs);
  const manualReviewRef = useRef(manualReview);

  // --- Human play state ---
  const [mode, setMode] = useState<"spectate" | "human">("spectate");
  const [handle, setHandle] = useState("");
  const [humanDifficulty, setHumanDifficulty] = useState<Difficulty>("medium");
  const [humanSeed, setHumanSeed] = useState(42);
  const [awaitingWeek, setAwaitingWeek] = useState<number | null>(null);
  const [pendingVerdicts, setPendingVerdicts] = useState<Record<string, PendingVerdict>>({});
  const [humanStarted, setHumanStarted] = useState(false);

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
    setCumulativeReward(0);
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

  async function startHumanGame() {
    stopRun();
    clearPlaybackQueue();
    setEvents([]);
    setCurrentWeek(undefined);
    setCumulativeReward(0);
    setSummary(undefined);
    setPendingVerdicts({});
    setAwaitingWeek(null);
    const seed = 42 + Math.floor(Math.random() * 10); // eval set 42-51
    setHumanSeed(seed);
    setHumanStarted(true);
    setStatus("created");
    setStatusMessage("Starting your game...");
    const humanConfig: RunConfig = {
      seed,
      policy: "heuristic",
      difficulty: humanDifficulty,
      weeks: 12,
      mode: "human",
      player_handle: handle.trim() || undefined,
    };
    const run = await createRun(humanConfig);
    const socket = openHumanPlay(run.run_id, handleHumanEvent);
    socketRef.current = socket;
  }

  function handleHumanEvent(event: OfficeEvent) {
    setEvents((prev) => [...prev.slice(-39), event]);
    if (event.type === "run_started") {
      setStatus("running");
      const nextMaxWeeks = event.payload.max_weeks;
      if (typeof nextMaxWeeks === "number") setMaxWeeks(nextMaxWeeks);
      setStatusMessage("You are the CEO. Review the inbox.");
    } else if (event.type === "week_started") {
      const payload = event.payload as unknown as WeekPayload;
      setCurrentWeek(payload);
      setPendingVerdicts({});
      setAwaitingWeek(payload.week);
      setStatusMessage(`Week ${payload.week}: decide on every proposal, then submit.`);
    } else if (event.type === "week_completed") {
      const payload = event.payload as unknown as WeekPayload;
      setCurrentWeek(payload);
      if (typeof payload.reward === "number") {
        setCumulativeReward((prev) => prev + (payload.reward ?? 0));
      }
      setStatusMessage(`Week ${payload.week} closed.`);
    } else if (event.type === "run_completed") {
      setStatus("completed");
      setSummary(event.payload);
      setAwaitingWeek(null);
      setStatusMessage("Quarter complete — see your results.");
      socketRef.current?.close();
      socketRef.current = null;
    } else if (event.type === "run_failed") {
      setStatus("failed");
      setStatusMessage(String(event.payload.message ?? "Run failed."));
      setAwaitingWeek(null);
    }
  }

  function submitWeek() {
    if (awaitingWeek === null || !socketRef.current) return;
    const decisions = buildDecisions(currentWeek, pendingVerdicts);
    sendDecisions(socketRef.current, awaitingWeek, decisions);
    setAwaitingWeek(null);
    setStatusMessage("Submitted — closing the week...");
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
      const payload = event.payload as unknown as WeekPayload;
      setCurrentWeek(payload);
      if (typeof payload.reward === "number") {
        setCumulativeReward((prev) => prev + (payload.reward ?? 0));
      }
      setStatusMessage(`Week ${payload.week} closed. Journal posted.`);
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

  const humanSummary = (summary?.summary as Record<string, number> | undefined) ?? undefined;

  return (
    <main className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">Retail CEO Pixel Office</p>
          <h1>Live CEO Command Floor</h1>
          <p>{headline}</p>
        </div>
        <div className="mode-toggle">
          <button className={mode === "spectate" ? "active" : ""} onClick={() => setMode("spectate")}>
            Watch a policy
          </button>
          <button className={mode === "human" ? "active" : ""} onClick={() => setMode("human")}>
            Play as CEO
          </button>
        </div>
      </header>

      {mode === "human" && !humanStarted && (
        <section className="pregame panel pixel-border">
          <h2>Play as CEO</h2>
          <label>
            Handle (optional):
            <input value={handle} onChange={(e) => setHandle(e.target.value)} maxLength={64} placeholder="anonymous" />
          </label>
          <label>
            Difficulty:
            <select value={humanDifficulty} onChange={(e) => setHumanDifficulty(e.target.value as Difficulty)}>
              <option value="easy">easy</option>
              <option value="medium">medium</option>
              <option value="hard">hard</option>
            </select>
          </label>
          <p>A seed from the official eval set (42–51) will be drawn when you start.</p>
          <button className="submit-week" onClick={startHumanGame}>Start game</button>
        </section>
      )}

      {mode === "human" && humanStarted && status === "completed" && humanSummary && (
        <section className="endscreen panel pixel-border">
          <h2>Quarter complete — {handle.trim() || "anonymous"}</h2>
          <p>Seed {humanSeed} · {humanDifficulty}</p>
          <p><strong>Your reward: {Number(humanSummary.total_reward ?? 0).toFixed(3)}</strong></p>
          <p>EBITDA {Number(humanSummary.ebitda_margin_pct ?? 0).toFixed(2)}% · final cash ₹{(Number(humanSummary.final_cash_inr ?? 0) / 1e7).toFixed(1)}Cr · stockout {Number(humanSummary.avg_stockout_pct ?? 0).toFixed(1)}% · NPS {Number(humanSummary.avg_nps ?? 0).toFixed(0)}</p>
          <p>Heuristic on {humanDifficulty}: {BASELINE_REWARDS[humanDifficulty].heuristic.toFixed(2)} · Oracle: {BASELINE_REWARDS[humanDifficulty].oracle.toFixed(2)}</p>
          <p className="recording-note">Recorded to {String(summary?.recording_path ?? "results/human/")}</p>
          <button className="submit-week" onClick={() => { setHumanStarted(false); setStatus("idle"); }}>Play again</button>
        </section>
      )}

      <section className="dashboard-grid">
        <div className="left-rail">
          <JournalPanel
            journal={journal}
            statusMessage={statusMessage}
            decisionKpi={journalDecisionKpi}
          />
          {mode === "human" && awaitingWeek !== null ? (
            <>
              <ProposalPanel
                week={currentWeek}
                interactive
                pendingVerdicts={pendingVerdicts}
                onSetVerdict={(pid, verdict, mp) =>
                  setPendingVerdicts((p) => ({ ...p, [pid]: { verdict, modified_params: mp } }))
                }
              />
              <button
                className="submit-week"
                disabled={!allDecided(currentWeek, pendingVerdicts)}
                onClick={submitWeek}
              >
                Submit Week {awaitingWeek}
              </button>
            </>
          ) : (
            <ProposalPanel week={currentWeek} />
          )}
        </div>
        <div className="office-stage">
          <TopKpiBar
            week={currentWeek}
            maxWeeks={maxWeeks}
            status={status}
            cumulativeReward={cumulativeReward}
          />
          <OfficeCanvas week={currentWeek} statusMessage={statusMessage} />
        </div>
        <div className="right-rail">
          {mode === "spectate" && (
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
          )}
          <KpiHud week={currentWeek} maxWeeks={maxWeeks} status={status} />
          <EventLog events={events} />
        </div>
      </section>
    </main>
  );
}

