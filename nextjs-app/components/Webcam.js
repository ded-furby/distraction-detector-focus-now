import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState
} from "react";
#this is the first knoy-code commit
function getDefaultWsUrl() {
  if (typeof window === "undefined") {
    return "ws://localhost:8000/ws/gaze";
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const hostname = window.location.hostname || "localhost";

  return `${protocol}://${hostname}:8000/ws/gaze`;
}

function wait(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

const Webcam = forwardRef(function Webcam(
  {
    fps = 12,
    wsUrl,
    onGazeUpdate,
    onCalibrationStateChange,
    onConnectionStateChange,
    onCameraStateChange,
    onSystemMessage
  },
  ref
) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const socketRef = useRef(null);
  const streamRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const frameIntervalRef = useRef(null);
  const calibrationCaptureRef = useRef(false);
  const unmountedRef = useRef(false);
  const callbacksRef = useRef({
    onGazeUpdate,
    onCalibrationStateChange,
    onConnectionStateChange,
    onCameraStateChange,
    onSystemMessage
  });

  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState("");
  const [connectionState, setConnectionState] = useState("connecting");

  useEffect(() => {
    callbacksRef.current = {
      onGazeUpdate,
      onCalibrationStateChange,
      onConnectionStateChange,
      onCameraStateChange,
      onSystemMessage
    };
  }, [
    onGazeUpdate,
    onCalibrationStateChange,
    onConnectionStateChange,
    onCameraStateChange,
    onSystemMessage
  ]);

  function emitConnection(nextState, errorMessage = "") {
    setConnectionState(nextState);
    callbacksRef.current.onConnectionStateChange?.({
      state: nextState,
      error: errorMessage
    });
  }

  function emitCamera(ready, errorMessage = "") {
    callbacksRef.current.onCameraStateChange?.({
      ready,
      error: errorMessage
    });
  }

  function emitSystemMessage(message, tone = "info") {
    callbacksRef.current.onSystemMessage?.({ message, tone });
  }

  function getFrameDataUrl() {
    const video = videoRef.current;
    const canvas = canvasRef.current;

    if (!video || !canvas || video.readyState < 2) {
      return null;
    }

    const width = video.videoWidth || 640;
    const height = video.videoHeight || 480;

    canvas.width = width;
    canvas.height = height;

    const context = canvas.getContext("2d", { willReadFrequently: false });

    if (!context) {
      return null;
    }

    context.drawImage(video, 0, 0, width, height);
    return canvas.toDataURL("image/jpeg", 0.74);
  }

  function sendJson(payload) {
    const socket = socketRef.current;

    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return false;
    }

    socket.send(JSON.stringify(payload));
    return true;
  }

  function connectSocket() {
    if (typeof window === "undefined") {
      return;
    }

    const targetUrl = wsUrl || getDefaultWsUrl();
    const socket = new WebSocket(targetUrl);
    socketRef.current = socket;
    emitConnection("connecting");

    socket.onopen = () => {
      if (unmountedRef.current) {
        return;
      }

      emitConnection("connected");
      emitSystemMessage("Backend connected. Live eye tracking is running.");
    };

    socket.onmessage = (event) => {
      if (unmountedRef.current) {
        return;
      }

      let payload;

      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        emitSystemMessage("Received an unreadable backend message.", "warning");
        return;
      }

      if (payload.type === "error") {
        emitSystemMessage(payload.message || "Backend returned an error.", "error");
        return;
      }

      if (payload.calibration && payload.type === "calibration") {
        callbacksRef.current.onCalibrationStateChange?.(payload.calibration);
      }

      if (payload.type === "gaze" || payload.type === "calibration") {
        callbacksRef.current.onGazeUpdate?.(payload);
      }

      if (payload.message) {
        emitSystemMessage(payload.message, payload.type === "error" ? "error" : "info");
      }
    };

    socket.onerror = () => {
      if (unmountedRef.current) {
        return;
      }

      emitConnection("error", "WebSocket error while talking to the backend.");
    };

    socket.onclose = () => {
      if (unmountedRef.current) {
        return;
      }

      emitConnection("disconnected");

      reconnectTimerRef.current = window.setTimeout(() => {
        connectSocket();
      }, 2000);
    };
  }

  useImperativeHandle(ref, () => ({
    async captureCalibration(point, options = {}) {
      if (calibrationCaptureRef.current) {
        return false;
      }

      const sampleCount = Math.max(options.samples || 12, 4);
      const intervalMs = Math.max(options.intervalMs || 90, 50);
      const onProgress = options.onProgress;

      calibrationCaptureRef.current = true;
      emitSystemMessage(`Capturing ${point} calibration burst...`);

      try {
        const images = [];

        for (let index = 0; index < sampleCount; index += 1) {
          const image = getFrameDataUrl();

          if (image) {
            images.push(image);
          }

          onProgress?.({
            current: index + 1,
            total: sampleCount
          });

          if (index < sampleCount - 1) {
            await wait(intervalMs);
          }
        }

        if (images.length < 4) {
          emitSystemMessage(
            "Not enough webcam frames were captured for calibration.",
            "warning"
          );
          return false;
        }

        const sent = sendJson({
          type: "calibrate-burst",
          point,
          images,
          sentAt: Date.now()
        });

        if (!sent) {
          emitSystemMessage(
            "Backend is not connected, so calibration could not be captured.",
            "warning"
          );
          return false;
        }

        return true;
      } finally {
        calibrationCaptureRef.current = false;
      }
    },
    resetCalibration() {
      const sent = sendJson({ type: "reset-calibration" });

      if (sent) {
        emitSystemMessage("Calibration reset on the backend.");
      }

      return sent;
    }
  }));

  useEffect(() => {
    unmountedRef.current = false;

    async function startCamera() {
      if (
        typeof navigator === "undefined" ||
        !navigator.mediaDevices?.getUserMedia
      ) {
        const message = "This browser does not support webcam capture.";
        setCameraError(message);
        emitCamera(false, message);
        emitSystemMessage(message, "error");
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 640 },
            height: { ideal: 480 },
            facingMode: "user"
          },
          audio: false
        });

        if (unmountedRef.current) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = stream;

        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          const playPromise = videoRef.current.play();

          if (playPromise?.catch) {
            playPromise.catch(() => {});
          }
        }
      } catch (error) {
        const message =
          error?.message || "Could not access the webcam. Check permissions.";
        setCameraError(message);
        emitCamera(false, message);
        emitSystemMessage(message, "error");
      }
    }

    startCamera();
    connectSocket();

    return () => {
      unmountedRef.current = true;

      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }

      if (frameIntervalRef.current) {
        window.clearInterval(frameIntervalRef.current);
      }

      if (socketRef.current) {
        socketRef.current.onclose = null;
        socketRef.current.close();
      }

      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, [wsUrl]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    if (frameIntervalRef.current) {
      window.clearInterval(frameIntervalRef.current);
    }

    frameIntervalRef.current = window.setInterval(() => {
      if (!cameraReady || calibrationCaptureRef.current) {
        return;
      }

      const image = getFrameDataUrl();

      if (!image) {
        return;
      }

      sendJson({
        type: "frame",
        image,
        sentAt: Date.now()
      });
    }, Math.max(Math.round(1000 / fps), 70));

    return () => {
      if (frameIntervalRef.current) {
        window.clearInterval(frameIntervalRef.current);
      }
    };
  }, [cameraReady, fps]);

  function handleLoadedMetadata() {
    setCameraError("");
    setCameraReady(true);
    emitCamera(true);
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Webcam feed</p>
          <h2>Live preview and stream</h2>
        </div>
      </div>

      <div className="preview-frame">
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          onLoadedMetadata={handleLoadedMetadata}
          className="webcam-video"
        />
        <canvas ref={canvasRef} hidden />
      </div>

      <div className="status-row">
        <span className="status-pill" data-tone={connectionState}>
          {connectionState}
        </span>
        <span
          className="status-pill"
          data-tone={cameraReady ? "success" : "warning"}
        >
          {cameraReady ? "camera live" : "camera pending"}
        </span>
        <span className="status-pill" data-tone="info">
          {fps} fps
        </span>
      </div>

      <p className="support-text">
        The browser sends JPEG frames to the Python backend in real time. Burst
        calibration temporarily pauses the normal stream so the eye samples stay
        clean.
      </p>

      {cameraError ? <p className="inline-error">{cameraError}</p> : null}
    </section>
  );
});

export default Webcam;
