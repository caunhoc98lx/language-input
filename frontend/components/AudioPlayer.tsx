"use client";

import { useEffect, useRef, useState } from "react";
import { formatDuration } from "@/lib/practice";
import type { PracticeSection } from "@/lib/practice";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

/**
 * Listening player.
 *
 * Exam mode is the real constraint: the recording plays once, straight through,
 * with no seeking and no speed control - which is what the test is. Learning
 * mode unlocks the scrub bar, speeds and replay.
 *
 * A section can point at a segment of a longer file (audio_start/end), so the
 * player clamps playback to that window.
 */
export default function AudioPlayer({
  sections,
  examMode,
}: {
  sections: PracticeSection[];
  examMode: boolean;
}) {
  const withAudio = sections.filter((s) => s.audio);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState(1);
  const [volume, setVolume] = useState(1);
  const [played, setPlayed] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  const section = withAudio[index];
  const start = section?.audio?.start ?? 0;
  const end = section?.audio?.end ?? null;
  const windowEnd = end ?? duration;
  const position = Math.max(0, time - start);
  const windowLength = Math.max(0, windowEnd - start);

  useEffect(() => {
    const el = audioRef.current;
    if (el) el.playbackRate = speed;
  }, [speed, index]);

  if (!section?.audio) return null;

  function selectSection(next: number) {
    const el = audioRef.current;
    if (el) el.pause();
    setIndex(next);
    setPlaying(false);
    setPlayed(false);
    setTime(withAudio[next]?.audio?.start ?? 0);
  }

  const src = `${API_URL}/api/library/files/${section.audio.file_id}/raw`;

  function toggle() {
    const el = audioRef.current;
    if (!el) return;
    if (playing) {
      el.pause();
      setPlaying(false);
      return;
    }
    if (el.currentTime < start || (end && el.currentTime > end)) el.currentTime = start;
    el.play();
    setPlaying(true);
    setPlayed(true);
  }

  function seek(to: number) {
    const el = audioRef.current;
    if (!el || examMode) return;
    el.currentTime = Math.min(Math.max(start + to, start), windowEnd || el.duration);
    setTime(el.currentTime);
  }

  return (
    <div className="card audio-player">
      <audio
        ref={audioRef}
        src={src}
        crossOrigin="use-credentials"
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => {
          const el = e.currentTarget;
          if (end && el.currentTime >= end) {
            el.pause();
            setPlaying(false);
          }
          setTime(el.currentTime);
        }}
        onEnded={() => setPlaying(false)}
      />

      <div className="audio-row">
        <button className="btn play-btn" onClick={toggle} disabled={examMode && played && !playing}>
          {playing ? "❚❚" : "▶"}
        </button>

        <div className="audio-track">
          <div className="audio-heads">
            <span>{withAudio.length > 1 ? section.title : "Recording"}</span>
            <span className="subtitle" style={{ margin: 0 }}>
              {formatDuration(Math.round(position))} / {formatDuration(Math.round(windowLength || 0))}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(1, Math.round(windowLength))}
            value={Math.round(position)}
            disabled={examMode}
            onChange={(e) => seek(Number(e.target.value))}
            aria-label="Seek"
          />
        </div>

        <label className="audio-control">
          Vol
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={volume}
            onChange={(e) => {
              setVolume(Number(e.target.value));
              if (audioRef.current) audioRef.current.volume = Number(e.target.value);
            }}
            aria-label="Volume"
          />
        </label>

        {!examMode && (
          <div className="speed-row">
            {SPEEDS.map((s) => (
              <button
                key={s}
                className={`chip-select ${speed === s ? "active" : ""}`}
                onClick={() => setSpeed(s)}
              >
                {s}×
              </button>
            ))}
          </div>
        )}
      </div>

      {withAudio.length > 1 && (
        <div className="speed-row" style={{ marginTop: 10 }}>
          {withAudio.map((s, i) => (
            <button
              key={s.id}
              className={`chip-select ${i === index ? "active" : ""}`}
              onClick={() => selectSection(i)}
            >
              {s.title}
            </button>
          ))}
        </div>
      )}

      {examMode && (
        <p className="subtitle" style={{ margin: "10px 0 0", fontSize: "0.8rem" }}>
          Exam mode: the recording plays once and cannot be rewound.
        </p>
      )}
    </div>
  );
}
