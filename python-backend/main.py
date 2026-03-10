from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState

from gaze_detector import GazeDetector, GazeMetrics
from utils import decode_data_url_to_bgr


CALIBRATION_ORDER = ("center", "left", "right", "up", "down")
MIN_TRACKING_CONFIDENCE = 0.16
MIN_CALIBRATION_SAMPLES = 4
DEFAULT_THRESHOLDS = {
    "horizontalCenter": 0.5,
    "verticalCenter": 0.5,
    "left": 0.36,
    "right": 0.64,
    "up": 0.38,
    "down": 0.62,
    "horizontalDeadzone": 0.05,
    "verticalDeadzone": 0.05,
}


@dataclass
class CalibrationCapture:
    horizontal: float
    vertical: float
    valid_frames: int


@dataclass
class CalibrationState:
    samples: dict[str, list[CalibrationCapture]] = field(
        default_factory=lambda: {point: [] for point in CALIBRATION_ORDER}
    )

    def reset(self) -> None:
        self.samples = {point: [] for point in CALIBRATION_ORDER}

    def add_capture(
        self, point: str, horizontal: float, vertical: float, valid_frames: int
    ) -> None:
        self.samples.setdefault(point, []).append(
            CalibrationCapture(
                horizontal=horizontal,
                vertical=vertical,
                valid_frames=valid_frames,
            )
        )

    def ready(self) -> bool:
        return all(self.samples.get(point) for point in CALIBRATION_ORDER)

    def next_point(self) -> str | None:
        for point in CALIBRATION_ORDER:
            if not self.samples.get(point):
                return point

        return None

    def averages(self) -> dict[str, dict[str, float | int | None]]:
        averages: dict[str, dict[str, float | int | None]] = {}

        for point in CALIBRATION_ORDER:
            captures = self.samples.get(point, [])

            if not captures:
                averages[point] = {
                    "horizontal": None,
                    "vertical": None,
                    "captures": 0,
                    "validFrames": 0,
                }
                continue

            total_frames = sum(capture.valid_frames for capture in captures)
            weight_total = max(total_frames, 1)
            horizontal = sum(
                capture.horizontal * capture.valid_frames for capture in captures
            ) / weight_total
            vertical = sum(
                capture.vertical * capture.valid_frames for capture in captures
            ) / weight_total

            averages[point] = {
                "horizontal": round(horizontal, 4),
                "vertical": round(vertical, 4),
                "captures": len(captures),
                "validFrames": total_frames,
            }

        return averages

    def thresholds(self) -> dict[str, float]:
        if not self.ready():
            return DEFAULT_THRESHOLDS.copy()

        averages = self.averages()
        center_horizontal = float(averages["center"]["horizontal"])
        center_vertical = float(averages["center"]["vertical"])
        left_horizontal = float(averages["left"]["horizontal"])
        right_horizontal = float(averages["right"]["horizontal"])
        up_vertical = float(averages["up"]["vertical"])
        down_vertical = float(averages["down"]["vertical"])

        left_threshold = center_horizontal + (left_horizontal - center_horizontal) * 0.55
        right_threshold = center_horizontal + (right_horizontal - center_horizontal) * 0.55
        up_threshold = center_vertical + (up_vertical - center_vertical) * 0.55
        down_threshold = center_vertical + (down_vertical - center_vertical) * 0.55

        horizontal_spread = max(
            abs(left_horizontal - center_horizontal),
            abs(right_horizontal - center_horizontal),
        )
        vertical_spread = max(
            abs(up_vertical - center_vertical),
            abs(down_vertical - center_vertical),
        )

        return {
            "horizontalCenter": round(center_horizontal, 4),
            "verticalCenter": round(center_vertical, 4),
            "left": round(left_threshold, 4),
            "right": round(right_threshold, 4),
            "up": round(up_threshold, 4),
            "down": round(down_threshold, 4),
            "horizontalDeadzone": round(
                max(min(horizontal_spread * 0.28, 0.12), 0.03), 4
            ),
            "verticalDeadzone": round(
                max(min(vertical_spread * 0.28, 0.12), 0.03), 4
            ),
        }

    def classify(
        self, horizontal_ratio: float | None, vertical_ratio: float | None
    ) -> tuple[str, str, str, dict[str, float]]:
        thresholds = self.thresholds()

        if horizontal_ratio is None or vertical_ratio is None:
            return "NO_EYES", "CENTER", "CENTER", thresholds

        horizontal_gaze = self._classify_axis(
            value=horizontal_ratio,
            center=thresholds["horizontalCenter"],
            negative_threshold=thresholds["left"],
            positive_threshold=thresholds["right"],
            deadzone=thresholds["horizontalDeadzone"],
            negative_label="LEFT",
            positive_label="RIGHT",
        )
        vertical_gaze = self._classify_axis(
            value=vertical_ratio,
            center=thresholds["verticalCenter"],
            negative_threshold=thresholds["up"],
            positive_threshold=thresholds["down"],
            deadzone=thresholds["verticalDeadzone"],
            negative_label="UP",
            positive_label="DOWN",
        )

        if vertical_gaze != "CENTER" and horizontal_gaze != "CENTER":
            overall_gaze = f"{vertical_gaze}_{horizontal_gaze}"
        elif vertical_gaze != "CENTER":
            overall_gaze = vertical_gaze
        elif horizontal_gaze != "CENTER":
            overall_gaze = horizontal_gaze
        else:
            overall_gaze = "CENTER"

        return overall_gaze, horizontal_gaze, vertical_gaze, thresholds

    def to_payload(self) -> dict[str, object]:
        averages = self.averages()

        return {
            "ready": self.ready(),
            "recommendedNext": self.next_point(),
            "points": {
                point: {
                    "captured": averages[point]["captures"] > 0,
                    "captures": averages[point]["captures"],
                    "validFrames": averages[point]["validFrames"],
                    "horizontal": averages[point]["horizontal"],
                    "vertical": averages[point]["vertical"],
                }
                for point in CALIBRATION_ORDER
            },
        }

    @staticmethod
    def _classify_axis(
        *,
        value: float,
        center: float,
        negative_threshold: float,
        positive_threshold: float,
        deadzone: float,
        negative_label: str,
        positive_label: str,
    ) -> str:
        if abs(value - center) <= deadzone:
            return "CENTER"

        negative_triggered = (
            value <= negative_threshold
            if negative_threshold < center
            else value >= negative_threshold
        )
        positive_triggered = (
            value <= positive_threshold
            if positive_threshold < center
            else value >= positive_threshold
        )

        if negative_triggered and positive_triggered:
            return (
                negative_label
                if abs(value - negative_threshold) < abs(value - positive_threshold)
                else positive_label
            )
        if negative_triggered:
            return negative_label
        if positive_triggered:
            return positive_label

        negative_direction = (negative_threshold - center) * (value - center)
        positive_direction = (positive_threshold - center) * (value - center)

        if negative_direction > positive_direction and negative_direction > 0:
            return negative_label
        if positive_direction > negative_direction and positive_direction > 0:
            return positive_label

        return "CENTER"


@dataclass
class SessionState:
    calibration: CalibrationState = field(default_factory=CalibrationState)
    horizontal_history: deque[float] = field(default_factory=lambda: deque(maxlen=6))
    vertical_history: deque[float] = field(default_factory=lambda: deque(maxlen=6))
    confidence_history: deque[float] = field(default_factory=lambda: deque(maxlen=6))
    detector: GazeDetector = field(default_factory=GazeDetector)

    def close(self) -> None:
        self.detector.close()

    def clear_tracking_history(self) -> None:
        self.horizontal_history.clear()
        self.vertical_history.clear()
        self.confidence_history.clear()

    def smooth(
        self, metrics: GazeMetrics
    ) -> dict[str, float] | None:
        if (
            not metrics.eyes_detected
            or metrics.horizontal_ratio is None
            or metrics.vertical_ratio is None
            or metrics.confidence < MIN_TRACKING_CONFIDENCE
        ):
            self.clear_tracking_history()
            return None

        self.horizontal_history.append(metrics.horizontal_ratio)
        self.vertical_history.append(metrics.vertical_ratio)
        self.confidence_history.append(metrics.confidence)

        return {
            "horizontal": round(
                sum(self.horizontal_history) / len(self.horizontal_history), 4
            ),
            "vertical": round(sum(self.vertical_history) / len(self.vertical_history), 4),
            "confidence": round(
                sum(self.confidence_history) / len(self.confidence_history), 4
            ),
        }


app = FastAPI(title="Eye Tracking Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def build_payload(
    *,
    session: SessionState,
    gaze: str,
    horizontal_gaze: str,
    vertical_gaze: str,
    face_detected: bool,
    eyes_detected: bool,
    raw_horizontal_ratio: float | None,
    raw_vertical_ratio: float | None,
    smoothed_horizontal_ratio: float | None,
    smoothed_vertical_ratio: float | None,
    raw_confidence: float | None,
    smoothed_confidence: float | None,
    eye_count: int,
    left_eye_confidence: float | None,
    right_eye_confidence: float | None,
    message_type: str = "gaze",
    message: str | None = None,
) -> dict[str, object]:
    thresholds = session.calibration.thresholds()

    return {
        "type": message_type,
        "message": message,
        "gaze": gaze,
        "horizontalGaze": horizontal_gaze,
        "verticalGaze": vertical_gaze,
        "faceDetected": face_detected,
        "eyesDetected": eyes_detected,
        "calibrated": session.calibration.ready(),
        "trackingBackend": session.detector.backend_name,
        "metrics": {
            "rawHorizontalRatio": raw_horizontal_ratio,
            "rawVerticalRatio": raw_vertical_ratio,
            "horizontalRatio": smoothed_horizontal_ratio,
            "verticalRatio": smoothed_vertical_ratio,
            "rawConfidence": raw_confidence,
            "confidence": smoothed_confidence,
            "eyeCount": eye_count,
            "leftEyeConfidence": left_eye_confidence,
            "rightEyeConfidence": right_eye_confidence,
        },
        "thresholds": thresholds,
        "calibration": session.calibration.to_payload(),
    }


@app.websocket("/ws/gaze")
async def gaze_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session = SessionState()

    await websocket.send_json(
        build_payload(
            session=session,
            gaze="WAITING",
            horizontal_gaze="CENTER",
            vertical_gaze="CENTER",
            face_detected=False,
            eyes_detected=False,
            raw_horizontal_ratio=None,
            raw_vertical_ratio=None,
            smoothed_horizontal_ratio=None,
            smoothed_vertical_ratio=None,
            raw_confidence=None,
            smoothed_confidence=None,
            eye_count=0,
            left_eye_confidence=None,
            right_eye_confidence=None,
            message_type="calibration",
            message="Connected. Calibrate center, left, right, up, and down using steady eye-only samples.",
        )
    )

    try:
        while True:
            payload = await websocket.receive_json()
            message_type = str(payload.get("type", "frame"))

            if message_type == "reset-calibration":
                session.calibration.reset()
                session.clear_tracking_history()

                await websocket.send_json(
                    build_payload(
                        session=session,
                        gaze="WAITING",
                        horizontal_gaze="CENTER",
                        vertical_gaze="CENTER",
                        face_detected=False,
                        eyes_detected=False,
                        raw_horizontal_ratio=None,
                        raw_vertical_ratio=None,
                        smoothed_horizontal_ratio=None,
                        smoothed_vertical_ratio=None,
                        raw_confidence=None,
                        smoothed_confidence=None,
                        eye_count=0,
                        left_eye_confidence=None,
                        right_eye_confidence=None,
                        message_type="calibration",
                        message="Calibration reset. Capture center, left, right, up, and down again.",
                    )
                )
                continue

            if message_type == "calibrate-burst":
                point = str(payload.get("point", "")).lower().strip()
                images = payload.get("images", [])

                if point not in CALIBRATION_ORDER:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Calibration point must be center, left, right, up, or down.",
                        }
                    )
                    continue

                if not isinstance(images, list) or len(images) < MIN_CALIBRATION_SAMPLES:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Calibration requires a burst of at least 4 frames.",
                        }
                    )
                    continue

                accepted_samples: list[tuple[float, float, float]] = []

                for image in images:
                    frame = decode_data_url_to_bgr(str(image))

                    if frame is None:
                        continue

                    metrics = session.detector.estimate(frame)

                    if (
                        not metrics.eyes_detected
                        or metrics.horizontal_ratio is None
                        or metrics.vertical_ratio is None
                        or metrics.confidence < MIN_TRACKING_CONFIDENCE
                    ):
                        continue

                    accepted_samples.append(
                        (
                            metrics.horizontal_ratio,
                            metrics.vertical_ratio,
                            metrics.confidence,
                        )
                    )

                if len(accepted_samples) < MIN_CALIBRATION_SAMPLES:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Too few stable eye samples were captured. Keep your head still, open your eyes clearly, and try again.",
                        }
                    )
                    continue

                average_horizontal = round(
                    sum(sample[0] for sample in accepted_samples) / len(accepted_samples),
                    4,
                )
                average_vertical = round(
                    sum(sample[1] for sample in accepted_samples) / len(accepted_samples),
                    4,
                )
                average_confidence = round(
                    sum(sample[2] for sample in accepted_samples) / len(accepted_samples),
                    4,
                )

                session.calibration.add_capture(
                    point=point,
                    horizontal=average_horizontal,
                    vertical=average_vertical,
                    valid_frames=len(accepted_samples),
                )
                session.clear_tracking_history()
                gaze, horizontal_gaze, vertical_gaze, _ = session.calibration.classify(
                    average_horizontal, average_vertical
                )

                await websocket.send_json(
                    build_payload(
                        session=session,
                        gaze=gaze,
                        horizontal_gaze=horizontal_gaze,
                        vertical_gaze=vertical_gaze,
                        face_detected=True,
                        eyes_detected=True,
                        raw_horizontal_ratio=average_horizontal,
                        raw_vertical_ratio=average_vertical,
                        smoothed_horizontal_ratio=average_horizontal,
                        smoothed_vertical_ratio=average_vertical,
                        raw_confidence=average_confidence,
                        smoothed_confidence=average_confidence,
                        eye_count=2,
                        left_eye_confidence=average_confidence,
                        right_eye_confidence=average_confidence,
                        message_type="calibration",
                        message=(
                            f"{point.title()} calibration captured with {len(accepted_samples)} stable eye frames."
                        ),
                    )
                )
                continue

            frame = decode_data_url_to_bgr(str(payload.get("image", "")))

            if frame is None:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Invalid frame payload. Could not decode image.",
                    }
                )
                continue

            metrics = session.detector.estimate(frame)
            left_eye_confidence = (
                round(metrics.left_eye.confidence, 4) if metrics.left_eye else None
            )
            right_eye_confidence = (
                round(metrics.right_eye.confidence, 4) if metrics.right_eye else None
            )

            if not metrics.face_detected:
                session.clear_tracking_history()
                await websocket.send_json(
                    build_payload(
                        session=session,
                        gaze="NO_FACE",
                        horizontal_gaze="CENTER",
                        vertical_gaze="CENTER",
                        face_detected=False,
                        eyes_detected=False,
                        raw_horizontal_ratio=None,
                        raw_vertical_ratio=None,
                        smoothed_horizontal_ratio=None,
                        smoothed_vertical_ratio=None,
                        raw_confidence=None,
                        smoothed_confidence=None,
                        eye_count=0,
                        left_eye_confidence=None,
                        right_eye_confidence=None,
                    )
                )
                continue

            smoothed = session.smooth(metrics)

            if smoothed is None:
                await websocket.send_json(
                    build_payload(
                        session=session,
                        gaze="NO_EYES",
                        horizontal_gaze="CENTER",
                        vertical_gaze="CENTER",
                        face_detected=True,
                        eyes_detected=False,
                        raw_horizontal_ratio=(
                            round(metrics.horizontal_ratio, 4)
                            if metrics.horizontal_ratio is not None
                            else None
                        ),
                        raw_vertical_ratio=(
                            round(metrics.vertical_ratio, 4)
                            if metrics.vertical_ratio is not None
                            else None
                        ),
                        smoothed_horizontal_ratio=None,
                        smoothed_vertical_ratio=None,
                        raw_confidence=round(metrics.confidence, 4),
                        smoothed_confidence=None,
                        eye_count=metrics.eye_count,
                        left_eye_confidence=left_eye_confidence,
                        right_eye_confidence=right_eye_confidence,
                    )
                )
                continue

            gaze, horizontal_gaze, vertical_gaze, _ = session.calibration.classify(
                smoothed["horizontal"], smoothed["vertical"]
            )

            await websocket.send_json(
                build_payload(
                    session=session,
                    gaze=gaze,
                    horizontal_gaze=horizontal_gaze,
                    vertical_gaze=vertical_gaze,
                    face_detected=True,
                    eyes_detected=True,
                    raw_horizontal_ratio=round(metrics.horizontal_ratio, 4),
                    raw_vertical_ratio=round(metrics.vertical_ratio, 4),
                    smoothed_horizontal_ratio=smoothed["horizontal"],
                    smoothed_vertical_ratio=smoothed["vertical"],
                    raw_confidence=round(metrics.confidence, 4),
                    smoothed_confidence=smoothed["confidence"],
                    eye_count=metrics.eye_count,
                    left_eye_confidence=left_eye_confidence,
                    right_eye_confidence=right_eye_confidence,
                )
            )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        if websocket.application_state != WebSocketState.DISCONNECTED:
            await websocket.close(code=1011, reason=str(exc))
    finally:
        session.close()
