"use client";

import { useMemo } from "react";

import { HealthDocBrand } from "@/components/common/HealthDocBrand";
import { useQueueStream } from "./useQueueStream";
import type { NowServing, StreamStatus } from "./types";

const STATUS_LABEL: Record<StreamStatus, string> = {
  connecting: "Connecting…",
  live: "Live",
  reconnecting: "Reconnecting…",
};

const STATUS_COLOUR: Record<StreamStatus, string> = {
  connecting: "#94a3b8",
  live: "#22c55e",
  reconnecting: "#f59e0b",
};

function CounterCard({ entry }: { entry: NowServing }) {
  return (
    <div
      style={{
        borderRadius: 24,
        padding: "2.5rem 2rem",
        background: "rgba(255,255,255,0.06)",
        border: "1px solid rgba(255,255,255,0.12)",
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
        minWidth: 0,
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: "clamp(1rem, 1.6vw, 1.5rem)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.62)",
        }}
      >
        {entry.room_number ? `Room ${entry.room_number}` : "Consulting room"}
      </p>

      {/* The number is the entire point of the screen. It is sized to be read
          from the far end of a corridor, which is why this uses vw rather than
          the app's normal type scale. */}
      <p
        style={{
          margin: 0,
          fontSize: "clamp(3.5rem, 11vw, 11rem)",
          fontWeight: 800,
          lineHeight: 1,
          letterSpacing: "-0.02em",
          fontVariantNumeric: "tabular-nums",
          wordBreak: "break-all",
        }}
      >
        {entry.token_display}
      </p>

      <p
        style={{
          margin: 0,
          fontSize: "clamp(1rem, 2vw, 2rem)",
          color: "rgba(255,255,255,0.86)",
        }}
      >
        {entry.doctor_name ?? "Doctor"}
      </p>
    </div>
  );
}

export function QueueDisplayBoard({ departmentId }: { departmentId: string | null }) {
  const { status, serving, receivedAny } = useQueueStream(departmentId);

  const counters = useMemo(
    () =>
      Object.values(serving).sort((a, b) =>
        (a.room_number ?? "").localeCompare(b.room_number ?? "", undefined, {
          numeric: true,
        }),
      ),
    [serving],
  );

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "linear-gradient(160deg, #0b1220 0%, #131f38 100%)",
        color: "#f8fafc",
        padding: "clamp(1.5rem, 4vw, 4rem)",
        display: "flex",
        flexDirection: "column",
        gap: "clamp(1.5rem, 3vw, 3rem)",
      }}
    >
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "clamp(1rem, 2vw, 2rem)", flexWrap: "wrap" }}>
          <HealthDocBrand
            size={64}
            preload
            subtitle="HMIS"
            nameClassName="text-xl sm:text-2xl"
            className="text-white"
            imageClassName="bg-white"
          />
          <h1 style={{ margin: 0, fontSize: "clamp(1.5rem, 3vw, 3rem)", fontWeight: 700 }}>
            Now serving
          </h1>
        </div>

        {/* Staff need to know the board is stale, and they cannot open a
            console on a wall-mounted TV. */}
        <p
          aria-live="polite"
          style={{ margin: 0, display: "flex", alignItems: "center", gap: "0.6rem", fontSize: "clamp(0.9rem, 1.2vw, 1.25rem)", color: "rgba(255,255,255,0.7)" }}
        >
          <span
            aria-hidden
            style={{ width: 12, height: 12, borderRadius: "50%", background: STATUS_COLOUR[status], display: "inline-block" }}
          />
          {STATUS_LABEL[status]}
        </p>
      </header>

      {!departmentId ? (
        <p style={{ fontSize: "clamp(1rem, 2vw, 1.75rem)", color: "rgba(255,255,255,0.72)" }}>
          No department selected. Open this screen as{" "}
          <code>/queue-display?department=&lt;department_id&gt;</code>.
        </p>
      ) : counters.length === 0 ? (
        <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "center", textAlign: "center" }}>
          <div>
            <p style={{ fontSize: "clamp(1.25rem, 2.5vw, 2.25rem)", margin: 0 }}>
              {receivedAny ? "No token is currently being called." : "Waiting for the next token to be called."}
            </p>
            {/* Honest about the gap rather than showing a blank board that
                looks like an empty waiting room. The stream carries events
                from now on; it does not replay what was called before this
                screen connected. */}
            {!receivedAny && (
              <p style={{ marginTop: "0.75rem", fontSize: "clamp(0.85rem, 1.2vw, 1.1rem)", color: "rgba(255,255,255,0.55)" }}>
                This board shows calls made from the moment it connected.
              </p>
            )}
          </div>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gap: "clamp(1rem, 2vw, 2rem)",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 22rem), 1fr))",
            flex: 1,
            alignContent: "start",
          }}
        >
          {counters.map((entry) => (
            <CounterCard key={entry.queue_id} entry={entry} />
          ))}
        </div>
      )}
    </main>
  );
}

export default QueueDisplayBoard;
