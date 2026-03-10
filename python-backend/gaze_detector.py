from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from utils import clamp


@dataclass
class EyeMeasurement:
    horizontal_ratio: float | None = None
    vertical_ratio: float | None = None
    confidence: float = 0.0


@dataclass
class GazeMetrics:
    face_detected: bool
    eyes_detected: bool = False
    vertical_ratio: float | None = None
    horizontal_ratio: float | None = None
    confidence: float = 0.0
    eye_count: int = 0
    left_eye: EyeMeasurement | None = None
    right_eye: EyeMeasurement | None = None


class LegacyMediaPipeFaceMeshBackend:
    LEFT_IRIS = [468, 469, 470, 471, 472]
    RIGHT_IRIS = [473, 474, 475, 476, 477]

    LEFT_EYE_CORNERS = [33, 133]
    RIGHT_EYE_CORNERS = [362, 263]

    LEFT_LIDS = (159, 145)
    RIGHT_LIDS = (386, 374)

    def __init__(self) -> None:
        try:
            from mediapipe import solutions as mp_solutions

            face_mesh_module = mp_solutions.face_mesh
        except (ImportError, AttributeError):
            raise RuntimeError("Legacy MediaPipe Face Mesh is not available.")

        self._face_mesh = face_mesh_module.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def close(self) -> None:
        self._face_mesh.close()

    def estimate(self, frame: np.ndarray) -> GazeMetrics:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb_frame)

        if not results.multi_face_landmarks:
            return GazeMetrics(face_detected=False)

        landmarks = results.multi_face_landmarks[0].landmark
        frame_height, frame_width = frame.shape[:2]

        left_eye = self._extract_eye_metrics(
            landmarks=landmarks,
            iris_indices=self.LEFT_IRIS,
            corner_indices=self.LEFT_EYE_CORNERS,
            lids=self.LEFT_LIDS,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        right_eye = self._extract_eye_metrics(
            landmarks=landmarks,
            iris_indices=self.RIGHT_IRIS,
            corner_indices=self.RIGHT_EYE_CORNERS,
            lids=self.RIGHT_LIDS,
            frame_width=frame_width,
            frame_height=frame_height,
        )

        usable_eyes = [eye for eye in (left_eye, right_eye) if eye is not None]

        if not usable_eyes:
            return GazeMetrics(face_detected=True, eyes_detected=False)

        vertical_ratio = float(
            np.mean([eye.vertical_ratio for eye in usable_eyes], dtype=np.float32)
        )
        horizontal_ratio = float(
            np.mean([eye.horizontal_ratio for eye in usable_eyes], dtype=np.float32)
        )
        confidence = float(
            np.mean([eye.confidence for eye in usable_eyes], dtype=np.float32)
        )

        return GazeMetrics(
            face_detected=True,
            eyes_detected=True,
            vertical_ratio=clamp(vertical_ratio),
            horizontal_ratio=clamp(horizontal_ratio),
            confidence=clamp(confidence),
            eye_count=len(usable_eyes),
            left_eye=left_eye,
            right_eye=right_eye,
        )

    def _extract_eye_metrics(
        self,
        *,
        landmarks,
        iris_indices: list[int],
        corner_indices: list[int],
        lids: tuple[int, int],
        frame_width: int,
        frame_height: int,
    ) -> EyeMeasurement | None:
        corner_a = self._scaled_landmark(
            landmarks, corner_indices[0], frame_width, frame_height
        )
        corner_b = self._scaled_landmark(
            landmarks, corner_indices[1], frame_width, frame_height
        )
        upper_lid = self._scaled_landmark(
            landmarks, lids[0], frame_width, frame_height
        )
        lower_lid = self._scaled_landmark(
            landmarks, lids[1], frame_width, frame_height
        )
        iris_points = np.array(
            [
                self._scaled_landmark(landmarks, idx, frame_width, frame_height)
                for idx in iris_indices
            ],
            dtype=np.float32,
        )

        iris_center = iris_points.mean(axis=0)
        left_edge = min(corner_a[0], corner_b[0])
        right_edge = max(corner_a[0], corner_b[0])
        top_edge = min(upper_lid[1], lower_lid[1])
        bottom_edge = max(upper_lid[1], lower_lid[1])

        eye_width = right_edge - left_edge
        eye_height = bottom_edge - top_edge

        if eye_width <= 1 or eye_height <= 1:
            return None

        return EyeMeasurement(
            horizontal_ratio=clamp(float((iris_center[0] - left_edge) / eye_width)),
            vertical_ratio=clamp(float((iris_center[1] - top_edge) / eye_height)),
            confidence=0.96,
        )

    @staticmethod
    def _scaled_landmark(landmarks, index: int, width: int, height: int) -> np.ndarray:
        landmark = landmarks[index]
        return np.array([landmark.x * width, landmark.y * height], dtype=np.float32)


class OpenCVEyeTrackerBackend:
    def __init__(self) -> None:
        self._clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
        )
        self._eye_tree_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml"
        )
        self._eye_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_eye.xml"
        )

        if self._face_cascade.empty():
            raise RuntimeError("OpenCV face cascade could not be loaded.")

        self._last_face_box: tuple[int, int, int, int] | None = None

    def close(self) -> None:
        return None

    def estimate(self, frame: np.ndarray) -> GazeMetrics:
        grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        grayscale = self._clahe.apply(grayscale)

        face_box = self._detect_face(grayscale)

        if face_box is None:
            self._last_face_box = None
            return GazeMetrics(face_detected=False)

        self._last_face_box = face_box

        left_box, right_box = self._detect_eye_boxes(grayscale, face_box)
        left_eye = self._analyze_eye(grayscale, left_box) if left_box else None
        right_eye = self._analyze_eye(grayscale, right_box) if right_box else None

        usable_eyes = [
            eye
            for eye in (left_eye, right_eye)
            if eye is not None and eye.horizontal_ratio is not None and eye.vertical_ratio is not None
        ]

        if not usable_eyes:
            return GazeMetrics(
                face_detected=True,
                eyes_detected=False,
                left_eye=left_eye,
                right_eye=right_eye,
            )

        weights = np.array(
            [max(eye.confidence, 0.05) for eye in usable_eyes], dtype=np.float32
        )

        horizontal_ratio = float(
            np.average(
                [eye.horizontal_ratio for eye in usable_eyes],
                weights=weights,
            )
        )
        vertical_ratio = float(
            np.average(
                [eye.vertical_ratio for eye in usable_eyes],
                weights=weights,
            )
        )
        confidence = float(np.mean(weights, dtype=np.float32))

        return GazeMetrics(
            face_detected=True,
            eyes_detected=confidence >= 0.15,
            vertical_ratio=clamp(vertical_ratio),
            horizontal_ratio=clamp(horizontal_ratio),
            confidence=clamp(confidence),
            eye_count=len(usable_eyes),
            left_eye=left_eye,
            right_eye=right_eye,
        )

    def _detect_face(
        self, grayscale: np.ndarray
    ) -> tuple[int, int, int, int] | None:
        faces = self._face_cascade.detectMultiScale(
            grayscale,
            scaleFactor=1.08,
            minNeighbors=6,
            minSize=(120, 120),
        )

        if len(faces) == 0:
            return None

        selected_face = max(
            faces,
            key=lambda candidate: self._score_face(candidate, self._last_face_box),
        )

        if self._last_face_box is None:
            return tuple(int(value) for value in selected_face)

        return self._smooth_box(self._last_face_box, selected_face, alpha=0.45)

    def _detect_eye_boxes(
        self,
        grayscale: np.ndarray,
        face_box: tuple[int, int, int, int],
    ) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
        face_x, face_y, face_w, face_h = face_box
        band_y = face_y + int(face_h * 0.14)
        band_h = max(int(face_h * 0.34), 40)
        band_x = face_x + int(face_w * 0.06)
        band_w = max(int(face_w * 0.88), 60)

        eye_band = grayscale[band_y : band_y + band_h, band_x : band_x + band_w]

        if eye_band.size == 0:
            return None, None

        mid_x = band_w // 2
        left_window = eye_band[:, :mid_x]
        right_window = eye_band[:, mid_x:]

        left_eye = self._pick_eye_box(left_window)
        right_eye = self._pick_eye_box(right_window)

        if left_eye is None:
            left_eye = self._fallback_eye_box(left_window)
        if right_eye is None:
            right_eye = self._fallback_eye_box(right_window)

        left_global = None
        right_global = None

        if left_eye is not None:
            left_global = (
                band_x + left_eye[0],
                band_y + left_eye[1],
                left_eye[2],
                left_eye[3],
            )

        if right_eye is not None:
            right_global = (
                band_x + mid_x + right_eye[0],
                band_y + right_eye[1],
                right_eye[2],
                right_eye[3],
            )

        return left_global, right_global

    def _pick_eye_box(
        self, eye_window: np.ndarray
    ) -> tuple[int, int, int, int] | None:
        if eye_window.size == 0:
            return None

        height, width = eye_window.shape[:2]
        min_width = max(int(width * 0.18), 20)
        min_height = max(int(height * 0.18), 12)

        detections = []

        for cascade in (self._eye_tree_cascade, self._eye_cascade):
            if cascade.empty():
                continue

            candidates = cascade.detectMultiScale(
                eye_window,
                scaleFactor=1.05,
                minNeighbors=5,
                minSize=(min_width, min_height),
                maxSize=(max(int(width * 0.92), min_width), max(int(height * 0.88), min_height)),
            )
            detections.extend(candidates)

        if not detections:
            return None

        return tuple(
            int(value)
            for value in max(
                detections,
                key=lambda detection: self._score_eye_box(detection, width, height),
            )
        )

    def _fallback_eye_box(
        self, eye_window: np.ndarray
    ) -> tuple[int, int, int, int] | None:
        if eye_window.size == 0:
            return None

        height, width = eye_window.shape[:2]

        return (
            int(width * 0.12),
            int(height * 0.16),
            max(int(width * 0.68), 24),
            max(int(height * 0.48), 14),
        )

    def _analyze_eye(
        self,
        grayscale: np.ndarray,
        eye_box: tuple[int, int, int, int],
    ) -> EyeMeasurement | None:
        frame_height, frame_width = grayscale.shape[:2]
        box_x, box_y, box_w, box_h = eye_box

        if box_w < 12 or box_h < 8:
            return None

        pad_x = int(box_w * 0.08)
        pad_y = int(box_h * 0.18)

        x0 = max(box_x - pad_x, 0)
        y0 = max(box_y - pad_y, 0)
        x1 = min(box_x + box_w + pad_x, frame_width)
        y1 = min(box_y + box_h + pad_y, frame_height)

        eye_region = grayscale[y0:y1, x0:x1]

        if eye_region.size == 0:
            return None

        eye_region = cv2.resize(
            eye_region, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC
        )
        eye_region = self._clahe.apply(eye_region)
        eye_region = cv2.GaussianBlur(eye_region, (7, 7), 0)

        region_height, region_width = eye_region.shape[:2]
        mask = np.zeros_like(eye_region, dtype=np.uint8)
        cv2.ellipse(
            mask,
            (region_width // 2, int(region_height * 0.58)),
            (int(region_width * 0.44), int(region_height * 0.28)),
            0,
            0,
            360,
            255,
            -1,
        )
        mask[: int(region_height * 0.16), :] = 0
        mask[int(region_height * 0.92) :, :] = 0

        masked_values = eye_region[mask > 0]

        if masked_values.size < 24:
            return None

        min_value, _, darkest_point, _ = cv2.minMaxLoc(eye_region, mask=mask)
        threshold_value = min(
            np.percentile(masked_values, 20) + 10,
            np.percentile(masked_values, 34),
        )

        binary = np.zeros_like(eye_region, dtype=np.uint8)
        binary[(eye_region <= threshold_value) & (mask > 0)] = 255

        kernel = np.ones((3, 3), dtype=np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        component = self._pick_pupil_component(
            binary=binary,
            eye_region=eye_region,
            mask=mask,
            darkest_point=darkest_point,
            min_value=min_value,
        )

        if component is None:
            center_x, center_y = darkest_point
            confidence = 0.14
        else:
            center_x, center_y, confidence = component

        usable_left = region_width * 0.15
        usable_right = region_width * 0.85
        usable_top = region_height * 0.24
        usable_bottom = region_height * 0.84

        horizontal_ratio = clamp(
            float((center_x - usable_left) / max(usable_right - usable_left, 1))
        )
        vertical_ratio = clamp(
            float((center_y - usable_top) / max(usable_bottom - usable_top, 1))
        )

        return EyeMeasurement(
            horizontal_ratio=horizontal_ratio,
            vertical_ratio=vertical_ratio,
            confidence=clamp(confidence),
        )

    def _pick_pupil_component(
        self,
        *,
        binary: np.ndarray,
        eye_region: np.ndarray,
        mask: np.ndarray,
        darkest_point: tuple[int, int],
        min_value: float,
    ) -> tuple[float, float, float] | None:
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            binary, connectivity=8
        )
        mask_area = max(int(np.count_nonzero(mask)), 1)
        best_component = None
        best_score = float("-inf")

        for label in range(1, num_labels):
            area = int(stats[label, cv2.CC_STAT_AREA])

            if area < mask_area * 0.003 or area > mask_area * 0.18:
                continue

            component_x = int(stats[label, cv2.CC_STAT_LEFT])
            component_y = int(stats[label, cv2.CC_STAT_TOP])
            component_w = int(stats[label, cv2.CC_STAT_WIDTH])
            component_h = int(stats[label, cv2.CC_STAT_HEIGHT])
            center_x, center_y = centroids[label]

            if component_w <= 0 or component_h <= 0:
                continue

            center_distance = np.hypot(
                (center_x - eye_region.shape[1] * 0.5) / max(eye_region.shape[1] * 0.5, 1),
                (center_y - eye_region.shape[0] * 0.58) / max(eye_region.shape[0] * 0.35, 1),
            )
            component_pixels = eye_region[labels == label]
            darkness_gain = float(np.mean(eye_region[mask > 0]) - np.mean(component_pixels))
            fill_ratio = area / max(component_w * component_h, 1)
            min_point_bonus = 16 if labels[darkest_point[1], darkest_point[0]] == label else 0

            score = (
                area * 0.7
                + darkness_gain * 3.8
                + fill_ratio * 36
                - center_distance * 32
                + min_point_bonus
            )

            if score > best_score:
                best_score = score
                area_ratio = area / mask_area
                confidence = (
                    0.22
                    + min(area_ratio / 0.05, 1.0) * 0.3
                    + clamp(darkness_gain / 40.0) * 0.28
                    + clamp(1.0 - center_distance) * 0.2
                )
                if min_value < 55:
                    confidence += 0.08

                best_component = (float(center_x), float(center_y), clamp(confidence))

        return best_component

    @staticmethod
    def _score_face(
        candidate: tuple[int, int, int, int],
        previous: tuple[int, int, int, int] | None,
    ) -> float:
        x, y, w, h = (int(value) for value in candidate)
        score = w * h

        if previous is None:
            return float(score)

        prev_x, prev_y, prev_w, prev_h = previous
        candidate_center = np.array([x + w / 2, y + h / 2], dtype=np.float32)
        previous_center = np.array(
            [prev_x + prev_w / 2, prev_y + prev_h / 2], dtype=np.float32
        )
        distance = np.linalg.norm(candidate_center - previous_center)

        return float(score - distance * 16)

    @staticmethod
    def _score_eye_box(
        candidate: tuple[int, int, int, int], width: int, height: int
    ) -> float:
        x, y, w, h = (int(value) for value in candidate)
        center_x = x + w / 2
        center_y = y + h / 2
        aspect_ratio = w / max(h, 1)

        return float(
            (w * h)
            - abs(center_x - width * 0.5) * 2.1
            - abs(center_y - height * 0.45) * 2.8
            - abs(aspect_ratio - 2.2) * 28
        )

    @staticmethod
    def _smooth_box(
        previous: tuple[int, int, int, int],
        current: tuple[int, int, int, int],
        *,
        alpha: float,
    ) -> tuple[int, int, int, int]:
        return tuple(
            int(round(prev * (1 - alpha) + curr * alpha))
            for prev, curr in zip(previous, current)
        )


class GazeDetector:
    def __init__(self) -> None:
        self.backend_name = "opencv-eye-roi"

        try:
            self._backend = LegacyMediaPipeFaceMeshBackend()
            self.backend_name = "mediapipe-face-mesh"
        except Exception:
            self._backend = OpenCVEyeTrackerBackend()

    def close(self) -> None:
        self._backend.close()

    def estimate(self, frame: np.ndarray) -> GazeMetrics:
        return self._backend.estimate(frame)
