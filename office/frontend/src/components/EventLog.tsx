import type { OfficeEvent } from "../types";

type Props = {
  events: OfficeEvent[];
};

export function EventLog({ events }: Props) {
  return (
    <section className="event-log panel pixel-border">
      <div className="panel-title">Run Events</div>
      <div className="event-list">
        {events.slice(-10).map((event, index) => (
          <div className="event-row" key={`${event.type}-${index}`}>
            <span>{event.type}</span>
            <small>{formatTime(event.ts)}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatTime(ts?: number): string {
  if (!ts) return "--:--:--";
  return new Date(ts * 1000).toLocaleTimeString();
}

