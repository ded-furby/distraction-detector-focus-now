# Eye-Tracking Video Control Web App

This workspace contains a complete two-part implementation:

- `nextjs-app/`: Next.js frontend for webcam capture, calibration, status, and video control
- `python-backend/`: FastAPI backend for webcam frame processing and gaze estimation

The frontend streams webcam frames over WebSocket to the backend. The backend uses the strongest locally available eye tracker in the current environment. In this workspace that means an eye-ROI tracker built with OpenCV cascades and pupil analysis, with five-point calibration for `center`, `left`, `right`, `up`, and `down`. The frontend starts `distraction.mp4` after 5 continuous seconds of calibrated downward gaze, and pauses immediately when the gaze leaves that region.

## Run the backend

```bash
cd /python-backend
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000

```

## Run the frontend

```bash
cd /nextjs-app
npm install
npm run dev
```

The frontend expects the backend WebSocket at `ws://localhost:8000/ws/gaze` by default.

If you need a different backend URL, set:

```bash
NEXT_PUBLIC_GAZE_WS_URL=ws://your-host:8000/ws/gaze
```

## Add the video

Place your video here after the project is ready:

`/Users/arjun/Documents/Playground/nextjs-app/public/distraction.mp4`

The player is already wired to that filename.

## Calibration flow

1. Allow webcam access.
2. Capture `CENTER`.
3. Capture `LEFT`.
4. Capture `RIGHT`.
5. Capture `UP`.
6. Capture `DOWN`.
7. Once calibration is ready, look down toward the video area for 5 seconds to start playback.
8. Look up again to pause immediately.

## Notes

- Frames are processed in memory only and are not stored.
- For best results, use Chrome and good front lighting.
- If the browser blocks autoplay with audio, interact with the video once to grant playback permission.
# distraction-detector-focus-now
