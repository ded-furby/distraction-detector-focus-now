import Head from "next/head";
import { useRef, useState } from "react";
import GazeStatus from "../components/GazeStatus";
import VideoPlayer from "../components/VideoPlayer";
import Webcam from "../components/Webcam";

const CALIBRATION_TARGETS = [
  {
    key: "center",
    label: "Center",
    instruction: "Look straight ahead at the center line and keep only your eyes steady."
  },
  {
    key: "left",
    label: "Left",
    instruction: "Move only your eyes to the left edge without turning your head."
  },
  {
    key: "right",
    label: "Right",
    instruction: "Move only your eyes to the right edge without turning your head."
  },
  {
    key: "up",
    label: "Up",
    instruction: "Look upward with your eyes while keeping your face still."
  },
  {
    key: "down",
    label: "Down",
    instruction: "Look down toward the video region using your eyes only."
  }
];

const CALIBRATION_LABELS = Object.fromEntries(
  CALIBRATION_TARGETS.map((target) => [target.key, target.label])
);

const EMPTY_CALIBRATION = {
  ready: false,
  recommendedNext: "center",
  points: {
    center: {
      captured: false,
      captures: 0,
      validFrames: 0,
      horizontal: null,
      vertical: null
    },
    left: {
      captured: false,
      captures: 0,
      validFrames: 0,
      horizontal: null,
      vertical: null
    },
    right: {
      captured: false,
      captures: 0,
      validFrames: 0,
      horizontal: null,
      vertical: null
    },
    up: {
      captured: false,
      captures: 0,
      validFrames: 0,
      horizontal: null,
      vertical: null
    },
    down: {
      captured: false,
      captures: 0,
      validFrames: 0,
      horizontal: null,
      vertical: null
    }
  }
};

const EMPTY_GAZE = {
  gaze: "WAITING",
  horizontalGaze: "CENTER",
  verticalGaze: "CENTER",
  faceDetected: false,
  eyesDetected: false,
  calibrated: false,
  trackingBackend: "waiting",
  metrics: {
    rawHorizontalRatio: null,
    rawVerticalRatio: null,
    horizontalRatio: null,
    verticalRatio: null,
    rawConfidence: null,
    confidence: null,
    eyeCount: 0,
    leftEyeConfidence: null,
    rightEyeConfidence: null
  },
  thresholds: {
    horizontalCenter: null,
    verticalCenter: null,
    left: null,
    right: null,
    up: null,
    down: null,
    horizontalDeadzone: null,
    verticalDeadzone: null
  }
};

export default function HomePage() {
  const webcamRef = useRef(null);
  const downStartedAtRef = useRef(null);
  const shouldPlayRef = useRef(false);

  const [gazeState, setGazeState] = useState(EMPTY_GAZE);
  const [calibrationState, setCalibrationState] = useState(EMPTY_CALIBRATION);
  const [connectionState, setConnectionState] = useState("connecting");
  const [cameraState, setCameraState] = useState({ ready: false, error: "" });
  const [downSeconds, setDownSeconds] = useState(0);
  const [shouldPlay, setShouldPlay] = useState(false);
  const [notice, setNotice] = useState({
    tone: "info",
    message:
      "Allow webcam access, then capture center, left, right, up, and down with short eye-only bursts."
  });
  const [captureState, setCaptureState] = useState({
    busy: false,
    point: "",
    current: 0,
    total: 0
  });
  const [playbackState, setPlaybackState] = useState({
    playing: false,
    blocked: false,
    error: ""
  });

  function setPlaybackIntent(nextValue) {
    shouldPlayRef.current = nextValue;
    setShouldPlay(nextValue);
  }

  function resetAttentionTimer() {
    downStartedAtRef.current = null;
    setDownSeconds(0);

    if (shouldPlayRef.current) {
      setPlaybackIntent(false);
    }
  }

  function handleGazeUpdate(payload) {
    if (payload.calibration) {
      setCalibrationState(payload.calibration);
    }

    const nextState = {
      gaze: payload.gaze || "NO_EYES",
      horizontalGaze: payload.horizontalGaze || "CENTER",
      verticalGaze: payload.verticalGaze || "CENTER",
      faceDetected: Boolean(payload.faceDetected),
      eyesDetected: Boolean(payload.eyesDetected),
      calibrated: Boolean(payload.calibrated),
      trackingBackend: payload.trackingBackend || "unknown",
      metrics: {
        rawHorizontalRatio: payload.metrics?.rawHorizontalRatio ?? null,
        rawVerticalRatio: payload.metrics?.rawVerticalRatio ?? null,
        horizontalRatio: payload.metrics?.horizontalRatio ?? null,
        verticalRatio: payload.metrics?.verticalRatio ?? null,
        rawConfidence: payload.metrics?.rawConfidence ?? null,
        confidence: payload.metrics?.confidence ?? null,
        eyeCount: payload.metrics?.eyeCount ?? 0,
        leftEyeConfidence: payload.metrics?.leftEyeConfidence ?? null,
        rightEyeConfidence: payload.metrics?.rightEyeConfidence ?? null
      },
      thresholds: {
        horizontalCenter: payload.thresholds?.horizontalCenter ?? null,
        verticalCenter: payload.thresholds?.verticalCenter ?? null,
        left: payload.thresholds?.left ?? null,
        right: payload.thresholds?.right ?? null,
        up: payload.thresholds?.up ?? null,
        down: payload.thresholds?.down ?? null,
        horizontalDeadzone: payload.thresholds?.horizontalDeadzone ?? null,
        verticalDeadzone: payload.thresholds?.verticalDeadzone ?? null
      }
    };

    setGazeState(nextState);

    const trackingDown =
      nextState.eyesDetected &&
      nextState.calibrated &&
      nextState.verticalGaze === "DOWN" &&
      (nextState.metrics.confidence ?? 0) >= 0.18;

    if (!trackingDown) {
      resetAttentionTimer();
      return;
    }

    const now = Date.now();

    if (!downStartedAtRef.current) {
      downStartedAtRef.current = now;
    }

    const elapsed = (now - downStartedAtRef.current) / 1000;
    setDownSeconds(elapsed);

    if (elapsed >= 5 && !shouldPlayRef.current) {
      setPlaybackIntent(true);
      setNotice({
        tone: "success",
        message:
          "Downward eye gaze held for 5 seconds. distraction.mp4 should now be playing."
      });
    }
  }

  function handleCalibrationStateChange(nextCalibration) {
    setCalibrationState(nextCalibration);

    if (captureState.busy) {
      return;
    }

    if (nextCalibration.ready) {
      setNotice({
        tone: "success",
        message:
          "Five-point calibration is complete. Look down toward the video area for 5 seconds to start distraction.mp4."
      });
      return;
    }

    const nextLabel = CALIBRATION_LABELS[nextCalibration.recommendedNext] || "Center";
    setNotice({
      tone: "info",
      message: `Calibration updated. Next capture: ${nextLabel}. Keep your head still and move only your eyes.`
    });
  }

  function handleConnectionStateChange(nextConnection) {
    setConnectionState(nextConnection.state);

    if (nextConnection.state === "connected") {
      setNotice((currentNotice) => {
        if (currentNotice.tone === "success") {
          return currentNotice;
        }

        return {
          tone: "info",
          message:
            "Backend connected. Center your face in the webcam, then capture the five eye calibration points."
        };
      });
    }

    if (nextConnection.error) {
      setNotice({
        tone: "error",
        message: nextConnection.error
      });
    }
  }

  function handleCameraStateChange(nextCameraState) {
    setCameraState(nextCameraState);

    if (nextCameraState.error) {
      setNotice({
        tone: "error",
        message: nextCameraState.error
      });
    }
  }

  function handleSystemMessage(message) {
    if (!message?.message) {
      return;
    }

    setNotice({
      tone: message.tone || "info",
      message: message.message
    });
  }

  function handlePlaybackStateChange(nextPlaybackState) {
    setPlaybackState(nextPlaybackState);

    if (nextPlaybackState.blocked) {
      setNotice({
        tone: "warning",
        message:
          nextPlaybackState.error ||
          "The browser blocked autoplay. Interact with the video once, then eye-control will resume."
      });
      return;
    }

    if (nextPlaybackState.error) {
      setNotice({
        tone: "warning",
        message: nextPlaybackState.error
      });
    }
  }

  async function handleCaptureCalibration(point) {
    setCaptureState({
      busy: true,
      point,
      current: 0,
      total: 12
    });
    setNotice({
      tone: "info",
      message: `Capturing ${CALIBRATION_LABELS[point]} with a short burst. Keep your head still and move only your eyes.`
    });

    try {
      const success = await webcamRef.current?.captureCalibration(point, {
        samples: 12,
        intervalMs: 90,
        onProgress: ({ current, total }) => {
          setCaptureState({
            busy: true,
            point,
            current,
            total
          });
        }
      });

      if (!success) {
        setNotice({
          tone: "warning",
          message:
            "Calibration capture failed. Make sure the webcam is active, your eyes are visible, and the backend is connected."
        });
      }
    } finally {
      setCaptureState({
        busy: false,
        point: "",
        current: 0,
        total: 0
      });
    }
  }

  function handleResetCalibration() {
    const success = webcamRef.current?.resetCalibration();

    if (!success) {
      setNotice({
        tone: "warning",
        message: "Could not reset calibration because the backend is not connected."
      });
      return;
    }

    setCalibrationState(EMPTY_CALIBRATION);
    setGazeState(EMPTY_GAZE);
    resetAttentionTimer();
    setNotice({
      tone: "info",
      message:
        "Calibration cleared. Re-capture center, left, right, up, and down with steady eye-only bursts."
    });
  }

  const countdown = Math.max(5 - downSeconds, 0);
  const canCaptureCalibration =
    connectionState === "connected" && cameraState.ready && !captureState.busy;
  const capturedCount = CALIBRATION_TARGETS.filter(
    (target) => calibrationState.points[target.key]?.captured
  ).length;
  const progressPercent = (capturedCount / CALIBRATION_TARGETS.length) * 100;
  const nextTargetLabel = calibrationState.ready
    ? "Calibration complete"
    : CALIBRATION_LABELS[calibrationState.recommendedNext] || "Center";

  return (
    <>
      <Head>
        <title>Eye Tracking Video Control</title>
        <meta
          name="description"
          content="Control distraction.mp4 with calibrated eye-only tracking."
        />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>

      <main className="app-shell">
        <section className="hero-panel">
          <div className="hero-copy">
            <p className="eyebrow">Next.js + FastAPI + Eye ROI Tracking</p>
            <h1>Calibrated eye control for distraction.mp4</h1>
            <p className="hero-text">
              The backend now tracks eye regions directly, calibrates five gaze
              directions with burst sampling, and exposes separate horizontal and
              vertical gaze so the 5-second downward trigger is steadier.
            </p>
          </div>

          <div className="hero-badges">
            <span className="status-pill" data-tone={connectionState}>
              Backend: {connectionState}
            </span>
            <span
              className="status-pill"
              data-tone={cameraState.ready ? "success" : "warning"}
            >
              Camera: {cameraState.ready ? "ready" : "waiting"}
            </span>
            <span
              className="status-pill"
              data-tone={calibrationState.ready ? "success" : "info"}
            >
              Calibration: {calibrationState.ready ? "ready" : `${capturedCount}/5`}
            </span>
            <span className="status-pill" data-tone="info">
              Tracker: {gazeState.trackingBackend}
            </span>
          </div>
        </section>

        <section className="panel panel-note" data-tone={notice.tone}>
          <p className="eyebrow">System note</p>
          <p>{notice.message}</p>
        </section>

        <section className="tracking-grid">
          <div className="panel-stack">
            <Webcam
              ref={webcamRef}
              fps={12}
              wsUrl={process.env.NEXT_PUBLIC_GAZE_WS_URL}
              onGazeUpdate={handleGazeUpdate}
              onCalibrationStateChange={handleCalibrationStateChange}
              onConnectionStateChange={handleConnectionStateChange}
              onCameraStateChange={handleCameraStateChange}
              onSystemMessage={handleSystemMessage}
            />

            <GazeStatus
              gaze={gazeState.gaze}
              horizontalGaze={gazeState.horizontalGaze}
              verticalGaze={gazeState.verticalGaze}
              faceDetected={gazeState.faceDetected}
              eyesDetected={gazeState.eyesDetected}
              calibrated={gazeState.calibrated}
              timerSeconds={downSeconds}
              countdownSeconds={countdown}
              connectionState={connectionState}
              cameraReady={cameraState.ready}
              trackingBackend={gazeState.trackingBackend}
              metrics={gazeState.metrics}
              thresholds={gazeState.thresholds}
              playbackState={playbackState}
            />
          </div>

          <section className="panel calibration-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Calibration</p>
                <h2>Five-point eye-only map</h2>
              </div>
              <span
                className="status-pill"
                data-tone={calibrationState.ready ? "success" : "info"}
              >
                {calibrationState.ready ? "ready" : `${capturedCount}/5 captured`}
              </span>
            </div>

            <p className="support-text">
              Each capture records a burst of 12 webcam frames and keeps only the
              stable eye samples. This makes left, right, up, down, and center
              thresholds noticeably less noisy than single-frame calibration.
            </p>

            <div className="progress-bar" aria-hidden="true">
              <span
                className="progress-fill"
                style={{ width: `${progressPercent}%` }}
              />
            </div>

            <div className="next-target">
              <strong>Next target:</strong> {nextTargetLabel}
            </div>

            <div className="calibration-stage">
              {CALIBRATION_TARGETS.map((target) => {
                const pointState = calibrationState.points[target.key];
                const isCapturing =
                  captureState.busy && captureState.point === target.key;

                return (
                  <div
                    className="calibration-row"
                    key={target.key}
                    data-point={target.key}
                  >
                    <div className="calibration-marker">
                      <span className="marker-dot" />
                      <div>
                        <strong>{target.label}</strong>
                        <p>{target.instruction}</p>
                      </div>
                    </div>

                    <div className="calibration-actions">
                      <button
                        type="button"
                        className="action-button"
                        onClick={() => handleCaptureCalibration(target.key)}
                        disabled={!canCaptureCalibration}
                      >
                        {isCapturing
                          ? `Capturing ${captureState.current}/${captureState.total}`
                          : `Capture ${target.label}`}
                      </button>
                      <span
                        className="status-pill"
                        data-tone={pointState?.captured ? "success" : "warning"}
                      >
                        {pointState?.captured
                          ? `${pointState.captures} burst`
                          : "pending"}
                      </span>
                      <span className="capture-meta">
                        {pointState?.captured
                          ? `${pointState.validFrames} stable frames`
                          : "12-frame burst"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="calibration-footer">
              <button
                type="button"
                className="ghost-button"
                onClick={handleResetCalibration}
                disabled={connectionState !== "connected" || captureState.busy}
              >
                Reset calibration
              </button>
              <p>
                Attention timer:{" "}
                <strong>
                  {gazeState.calibrated && gazeState.verticalGaze === "DOWN"
                    ? `${downSeconds.toFixed(1)}s / 5.0s`
                    : "waiting for calibrated DOWN gaze"}
                </strong>
              </p>
            </div>
          </section>
        </section>

        <div className="video-section">
          <VideoPlayer
            shouldPlay={shouldPlay}
            src="/distraction.mp4"
            onPlaybackStateChange={handlePlaybackStateChange}
          />
        </div>
      </main>
    </>
  );
}
