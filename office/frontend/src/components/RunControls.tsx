import type { RunConfig } from "../types";

type Props = {
  config: RunConfig;
  running: boolean;
  playbackDelayMs: number;
  manualReview: boolean;
  queuedEventsCount: number;
  onChange: (next: RunConfig) => void;
  onPlaybackDelayChange: (delayMs: number) => void;
  onManualReviewChange: (manualReview: boolean) => void;
  onNextEvent: () => void;
  onStart: () => void;
  onStop: () => void;
};

export function RunControls({
  config,
  running,
  playbackDelayMs,
  manualReview,
  queuedEventsCount,
  onChange,
  onPlaybackDelayChange,
  onManualReviewChange,
  onNextEvent,
  onStart,
  onStop,
}: Props) {
  return (
    <section className="run-controls panel pixel-border">
      <div className="panel-title inline-title">Run Controls</div>
      <label>
        Seed
        <input
          type="number"
          value={config.seed}
          onChange={(event) => onChange({ ...config, seed: Number(event.target.value) })}
          disabled={running}
        />
      </label>
      <label>
        Policy
        <select
          value={config.policy}
          onChange={(event) => onChange({ ...config, policy: event.target.value as RunConfig["policy"] })}
          disabled={running}
        >
          <option value="heuristic">Heuristic (rule-based)</option>
          <option value="oracle">Oracle (privileged)</option>
          <option value="all_approve">All Approve</option>
          <option value="random">Random</option>
        </select>
        <span className="control-hint">Scripted, CPU-only policies. No API keys required.</span>
      </label>
      <label>
        Difficulty
        <select
          value={config.difficulty}
          onChange={(event) => onChange({ ...config, difficulty: event.target.value as RunConfig["difficulty"] })}
          disabled={running}
        >
          <option value="easy">Easy</option>
          <option value="medium">Medium</option>
          <option value="hard">Hard</option>
        </select>
      </label>
      <label>
        Weeks
        <input
          type="number"
          min={1}
          max={52}
          value={config.weeks}
          onChange={(event) => onChange({ ...config, weeks: Number(event.target.value) })}
          disabled={running}
        />
      </label>
      <label>
        Review mode
        <span className="checkbox-row">
          <input
            type="checkbox"
            checked={manualReview}
            onChange={(event) => onManualReviewChange(event.target.checked)}
          />
          Manual next-step
        </span>
        <span className="control-hint">
          {manualReview
            ? "Pause after each streamed UI event."
            : "Auto-play streamed UI events."}
        </span>
      </label>
      {!manualReview && (
        <label>
          Step flow delay
          <input
            type="range"
            min="0"
            max="2000"
            step="100"
            value={playbackDelayMs}
            onChange={(event) => onPlaybackDelayChange(Number(event.target.value))}
          />
          <span className="control-hint">
            {playbackDelayMs === 0 ? "instant" : `${playbackDelayMs}ms between UI events`}
          </span>
        </label>
      )}
      {manualReview && (
        <button
          className="next-button"
          onClick={onNextEvent}
          disabled={queuedEventsCount === 0}
        >
          Next step ({queuedEventsCount})
        </button>
      )}
      <button className="start-button" onClick={onStart} disabled={running}>
        Start Live Run
      </button>
      <button className="stop-button" onClick={onStop} disabled={!running}>
        Stop
      </button>
    </section>
  );
}

