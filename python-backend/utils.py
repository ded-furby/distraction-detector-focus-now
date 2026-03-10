from __future__ import annotations

import base64

import cv2
import numpy as np


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def decode_data_url_to_bgr(data_url: str) -> np.ndarray | None:
    if not data_url:
        return None

    encoded = data_url.split(",", 1)[1] if "," in data_url else data_url

    try:
        image_bytes = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None

    image_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(image_buffer, cv2.IMREAD_COLOR)

    return frame
