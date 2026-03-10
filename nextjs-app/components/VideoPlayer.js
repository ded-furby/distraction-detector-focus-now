import { useEffect, useRef } from "react";

export default function VideoPlayer({
  shouldPlay,
  src = "/distraction.mp4",
  onPlaybackStateChange
}) {
  const videoRef = useRef(null);
  const callbackRef = useRef(onPlaybackStateChange);

  useEffect(() => {
    callbackRef.current = onPlaybackStateChange;
  }, [onPlaybackStateChange]);

  useEffect(() => {
    const video = videoRef.current;

    if (!video) {
      return;
    }

    if (!shouldPlay) {
      video.pause();
      callbackRef.current?.({
        playing: false,
        blocked: false,
        error: ""
      });
      return;
    }

    const playPromise = video.play();

    if (!playPromise?.then) {
      callbackRef.current?.({
        playing: !video.paused,
        blocked: false,
        error: ""
      });
      return;
    }

    playPromise
      .then(() => {
        callbackRef.current?.({
          playing: true,
          blocked: false,
          error: ""
        });
      })
      .catch((error) => {
        callbackRef.current?.({
          playing: false,
          blocked: true,
          error:
            error?.message ||
            "Browser playback was blocked until you interact with the video."
        });
      });
  }, [shouldPlay]);

  function handleVideoError() {
    callbackRef.current?.({
      playing: false,
      blocked: false,
      error:
        "Video file missing. Add distraction.mp4 to nextjs-app/public to enable playback."
    });
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <p className="eyebrow">Video target</p>
        <h2>Automatic playback region</h2>
      </div>

      <div className="video-shell">
        <video
          ref={videoRef}
          src={src}
          controls
          playsInline
          preload="metadata"
          onError={handleVideoError}
          className="video-player"
        />
      </div>

      <p className="support-text">
        This player is already bound to <code>distraction.mp4</code>. Once you
        place the file in <code>nextjs-app/public</code>, gaze control is ready.
      </p>
    </section>
  );
}
