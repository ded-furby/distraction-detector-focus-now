function formatMetric(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }

  return value.toFixed(3);
}

export default function GazeStatus({
  gaze,
  horizontalGaze,
  verticalGaze,
  faceDetected,
  eyesDetected,
  calibrated,
  timerSeconds,
  countdownSeconds,
  connectionState,
  cameraReady,
  trackingBackend,
  metrics,
  thresholds,
  playbackState
}) {
  const playbackLabel = playbackState.playing ? "PLAYING" : "PAUSED";

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Gaze status</p>
          <h2>Eye tracking feedback</h2>
        </div>
        <span className="status-pill" data-tone="info">
          {trackingBackend}
        </span>
      </div>

      <div className="status-row">
        <span className="status-pill" data-tone={connectionState}>
          backend {connectionState}
        </span>
        <span className="status-pill" data-tone={cameraReady ? "success" : "warning"}>
          camera {cameraReady ? "ready" : "waiting"}
        </span>
        <span className="status-pill" data-tone={calibrated ? "success" : "info"}>
          calibration {calibrated ? "ready" : "needed"}
        </span>
        <span className="status-pill" data-tone={eyesDetected ? "success" : "warning"}>
          eyes {eyesDetected ? "tracked" : "not locked"}
        </span>
        <span
          className="status-pill"
          data-tone={playbackState.playing ? "success" : "warning"}
        >
          video {playbackLabel.toLowerCase()}
        </span>
      </div>

      <div className="metric-grid">
        <article className="metric-card">
          <span>Overall gaze</span>
          <strong>{faceDetected ? gaze : "NO FACE"}</strong>
        </article>
        <article className="metric-card">
          <span>Horizontal</span>
          <strong>{eyesDetected ? horizontalGaze : "CENTER"}</strong>
        </article>
        <article className="metric-card">
          <span>Vertical</span>
          <strong>{eyesDetected ? verticalGaze : "CENTER"}</strong>
        </article>
        <article className="metric-card">
          <span>Eye count</span>
          <strong>{metrics.eyeCount || 0}</strong>
        </article>
        <article className="metric-card">
          <span>Timer</span>
          <strong>{timerSeconds.toFixed(1)}s</strong>
        </article>
        <article className="metric-card">
          <span>Countdown</span>
          <strong>{countdownSeconds.toFixed(1)}s</strong>
        </article>
      </div>

      <div className="detail-grid">
        <div>
          <span>Smoothed horizontal</span>
          <strong>{formatMetric(metrics.horizontalRatio)}</strong>
        </div>
        <div>
          <span>Smoothed vertical</span>
          <strong>{formatMetric(metrics.verticalRatio)}</strong>
        </div>
        <div>
          <span>Raw horizontal</span>
          <strong>{formatMetric(metrics.rawHorizontalRatio)}</strong>
        </div>
        <div>
          <span>Raw vertical</span>
          <strong>{formatMetric(metrics.rawVerticalRatio)}</strong>
        </div>
        <div>
          <span>Tracking confidence</span>
          <strong>{formatMetric(metrics.confidence)}</strong>
        </div>
        <div>
          <span>Raw confidence</span>
          <strong>{formatMetric(metrics.rawConfidence)}</strong>
        </div>
        <div>
          <span>Left threshold</span>
          <strong>{formatMetric(thresholds.left)}</strong>
        </div>
        <div>
          <span>Right threshold</span>
          <strong>{formatMetric(thresholds.right)}</strong>
        </div>
        <div>
          <span>Up threshold</span>
          <strong>{formatMetric(thresholds.up)}</strong>
        </div>
        <div>
          <span>Down threshold</span>
          <strong>{formatMetric(thresholds.down)}</strong>
        </div>
        <div>
          <span>Horizontal deadzone</span>
          <strong>{formatMetric(thresholds.horizontalDeadzone)}</strong>
        </div>
        <div>
          <span>Vertical deadzone</span>
          <strong>{formatMetric(thresholds.verticalDeadzone)}</strong>
        </div>
      </div>

      {playbackState.error ? (
        <p className="inline-error">{playbackState.error}</p>
      ) : null}
    </section>
  );
}
