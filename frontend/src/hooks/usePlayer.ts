import { useCallback, useEffect, useRef, useState } from "react";
import type { AuditEvent } from "../api/types";
import { bubbleFor, pulsesFor, type Bubble, type Pulse } from "../lib/runModel";

const LIVE_STEP_MS = 420;
const REPLAY_STEP_MS = 700;
const CATCH_UP_MS = 60;
const QUIET_STEP_MS = 120;

/**
 * Plays the events of one run into the team graph one by one, so every hand-off is visible.
 * Opening a finished run shows its final state at once; new live events and replays are animated.
 */
export function usePlayer(runKey: string | null, events: AuditEvent[], live: boolean) {
  const [played, setPlayed] = useState(events.length);
  const [replaying, setReplaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const [bubble, setBubble] = useState<Bubble | null>(null);
  const keyRef = useRef(runKey);
  const bubbleTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (keyRef.current !== runKey) {
      keyRef.current = runKey;
      setPlayed(live ? Math.max(0, events.length - 1) : events.length);
      setReplaying(false);
      setPulses([]);
      setBubble(null);
    }
  }, [runKey, events.length, live]);

  useEffect(() => {
    if (played >= events.length) {
      if (replaying) setReplaying(false);
      return;
    }
    const e = events[played];
    const animate = live || replaying;
    // only a live run falls behind; a replay always plays every step
    const catchUp = live && !replaying && events.length - played > 12;
    const visible = pulsesFor(e).length > 0 || bubbleFor(e) !== null;
    const step = (replaying ? REPLAY_STEP_MS : LIVE_STEP_MS) / speed;
    const delay = !animate ? 0 : catchUp ? CATCH_UP_MS : visible ? step : Math.min(step, QUIET_STEP_MS);
    const t = window.setTimeout(() => {
      if (animate && !catchUp) {
        const fresh = pulsesFor(e).map((p, i) => ({ ...p, id: `${e.seq}-${i}-${Date.now()}` }));
        if (fresh.length) setPulses((prev) => [...prev.slice(-14), ...fresh]);
        const b = bubbleFor(e);
        if (b) {
          setBubble(b);
          window.clearTimeout(bubbleTimer.current);
          bubbleTimer.current = window.setTimeout(() => setBubble(null), Math.max(2600, 4200 / speed));
        }
      }
      setPlayed((p) => p + 1);
    }, delay);
    return () => window.clearTimeout(t);
  }, [played, events, live, replaying, speed]);

  const replay = useCallback(() => {
    setPulses([]);
    setBubble(null);
    setPlayed(0);
    setReplaying(true);
  }, []);

  const skip = useCallback(() => {
    setReplaying(false);
    setPlayed(events.length);
    setPulses([]);
  }, [events.length]);

  const removePulse = useCallback((id: string) => setPulses((prev) => prev.filter((p) => p.id !== id)), []);

  return {
    played: Math.min(played, events.length),
    playedEvents: events.slice(0, Math.min(played, events.length)),
    pulses,
    bubble,
    replaying,
    speed,
    setSpeed,
    replay,
    skip,
    removePulse,
  };
}
