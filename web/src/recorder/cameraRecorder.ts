import {
  FaceLandmarker,
  FilesetResolver,
  PoseLandmarker,
  type FaceLandmarkerResult,
  type PoseLandmarkerResult,
} from "@mediapipe/tasks-vision";

const WASM = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm";
const FACE_MODEL =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const POSE_MODEL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task";

const FOREHEAD = [10, 151, 9, 8, 107, 336];
const LEFT_CHEEK = [234, 93, 132, 58, 172, 136];
const RIGHT_CHEEK = [454, 323, 361, 288, 397, 365];
const KEY_FACE = [
  10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 2, 234, 93, 132, 58, 172, 136, 150,
  149, 176, 148, 152, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 61, 291,
  13, 14, 78, 308, 33, 263, 133, 362,
];

export type FaceFrame = {
  t_perf: number;
  t_epoch: number;
  video_ts: number;
  blendshapes: Record<string, number>;
  pose: Array<{ x: number; y: number; z: number; v: number }>;
  face_key: Array<{ i: number; x: number; y: number; z: number }>;
  face_full?: Array<{ x: number; y: number; z: number }>;
  rgb: {
    forehead: [number, number, number] | null;
    leftCheek: [number, number, number] | null;
    rightCheek: [number, number, number] | null;
  };
  bbox: { x: number; y: number; w: number; h: number } | null;
};

let faceLm: FaceLandmarker | null = null;
let poseLm: PoseLandmarker | null = null;
let modelsPromise: Promise<void> | null = null;

export function loadVisionModels(): Promise<void> {
  if (!modelsPromise) {
    modelsPromise = (async () => {
      const files = await FilesetResolver.forVisionTasks(WASM);
      faceLm = await FaceLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: FACE_MODEL },
        runningMode: "VIDEO",
        numFaces: 1,
        outputFaceBlendshapes: true,
        outputFacialTransformationMatrixes: false,
      });
      poseLm = await PoseLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: POSE_MODEL },
        runningMode: "VIDEO",
        numPoses: 1,
      });
    })();
  }
  return modelsPromise;
}

function meanRgb(
  ctx: CanvasRenderingContext2D,
  points: Array<{ x: number; y: number }>,
  w: number,
  h: number,
): [number, number, number] | null {
  if (!points.length) return null;
  const xs = points.map((p) => Math.max(0, Math.min(w - 1, Math.round(p.x * w))));
  const ys = points.map((p) => Math.max(0, Math.min(h - 1, Math.round(p.y * h))));
  const minX = Math.max(0, Math.min(...xs) - 3);
  const minY = Math.max(0, Math.min(...ys) - 3);
  const maxX = Math.min(w - 1, Math.max(...xs) + 3);
  const maxY = Math.min(h - 1, Math.max(...ys) + 3);
  const rw = Math.max(1, maxX - minX + 1);
  const rh = Math.max(1, maxY - minY + 1);
  const img = ctx.getImageData(minX, minY, rw, rh).data;
  let r = 0,
    g = 0,
    b = 0,
    n = 0;
  for (let i = 0; i < img.length; i += 16) {
    r += img[i];
    g += img[i + 1];
    b += img[i + 2];
    n += 1;
  }
  return n ? [r / n, g / n, b / n] : null;
}

function packFace(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  face: FaceLandmarkerResult,
  pose: PoseLandmarkerResult,
  videoTs: number,
  fullMesh: boolean,
): FaceFrame {
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
  if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
  }
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const lm = face.faceLandmarks?.[0];
  const rgb = {
    forehead: lm ? meanRgb(ctx, FOREHEAD.map((i) => lm[i]).filter(Boolean), canvas.width, canvas.height) : null,
    leftCheek: lm ? meanRgb(ctx, LEFT_CHEEK.map((i) => lm[i]).filter(Boolean), canvas.width, canvas.height) : null,
    rightCheek: lm ? meanRgb(ctx, RIGHT_CHEEK.map((i) => lm[i]).filter(Boolean), canvas.width, canvas.height) : null,
  };
  const blend: Record<string, number> = {};
  for (const cat of face.faceBlendshapes?.[0]?.categories ?? []) {
    blend[cat.categoryName] = cat.score;
  }
  let bbox: FaceFrame["bbox"] = null;
  if (lm) {
    let minX = 1,
      minY = 1,
      maxX = 0,
      maxY = 0;
    for (const p of lm) {
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x);
      maxY = Math.max(maxY, p.y);
    }
    bbox = { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
  }
  const posePts = (pose.landmarks?.[0] ?? []).map((p) => ({
    x: round4(p.x),
    y: round4(p.y),
    z: round4(p.z),
    v: round4(p.visibility ?? 0),
  }));
  const face_key = lm
    ? KEY_FACE.filter((i) => lm[i]).map((i) => ({
        i,
        x: round4(lm[i].x),
        y: round4(lm[i].y),
        z: round4(lm[i].z),
      }))
    : [];
  const frame: FaceFrame = {
    t_perf: performance.now(),
    t_epoch: Date.now(),
    video_ts: videoTs,
    blendshapes: blend,
    pose: posePts,
    face_key,
    rgb,
    bbox,
  };
  if (fullMesh && lm) {
    frame.face_full = lm.map((p) => ({ x: round4(p.x), y: round4(p.y), z: round4(p.z) }));
  }
  return frame;
}

function round4(n: number) {
  return Math.round(n * 10000) / 10000;
}

export type CameraHandle = {
  video: HTMLVideoElement;
  stream: MediaStream;
  settings: MediaTrackSettings;
  stop: () => Promise<void>;
};

export async function startCamera(opts: {
  recordVideo: boolean;
  landmarks: boolean;
  onFace: (f: FaceFrame) => void;
  onVideoChunk: (blob: Blob, index: number) => void;
  preview?: HTMLVideoElement | null;
}): Promise<CameraHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: {
      width: { ideal: 640 },
      height: { ideal: 480 },
      frameRate: { ideal: 30 },
      facingMode: "user",
    },
    audio: false,
  });
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.srcObject = stream;
  await video.play();
  if (opts.preview) {
    opts.preview.srcObject = stream;
    await opts.preview.play().catch(() => undefined);
  }

  const track = stream.getVideoTracks()[0];
  const settings = track.getSettings();
  const canvas = document.createElement("canvas");

  let recorder: MediaRecorder | null = null;
  let chunkIndex = 0;
  if (opts.recordVideo) {
    const mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
      ? "video/webm;codecs=vp9"
      : MediaRecorder.isTypeSupported("video/webm;codecs=vp8")
        ? "video/webm;codecs=vp8"
        : MediaRecorder.isTypeSupported("video/mp4")
          ? "video/mp4"
          : "video/webm";
    recorder = new MediaRecorder(stream, {
      mimeType: mime,
      videoBitsPerSecond: 10_000_000,
    });
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) {
        opts.onVideoChunk(ev.data, chunkIndex++);
      }
    };
    recorder.start(5000);
  }

  let raf = 0;
  let running = true;
  let lastTs = -1;
  let frameCount = 0;
  if (opts.landmarks) {
    await loadVisionModels();
    const loop = () => {
      if (!running) return;
      const ts = performance.now();
      if (video.readyState >= 2 && faceLm && poseLm && ts !== lastTs) {
        lastTs = ts;
        try {
          const face = faceLm.detectForVideo(video, ts);
          const pose = poseLm.detectForVideo(video, ts);
          const full = frameCount % 3 === 0;
          opts.onFace(packFace(video, canvas, face, pose, ts, full));
          frameCount += 1;
        } catch {
          /* model not ready for this frame */
        }
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
  }

  return {
    video,
    stream,
    settings,
    stop: async () => {
      running = false;
      cancelAnimationFrame(raf);
      if (recorder && recorder.state !== "inactive") {
        await new Promise<void>((resolve) => {
          recorder!.onstop = () => resolve();
          recorder!.stop();
        });
      }
      for (const t of stream.getTracks()) t.stop();
    },
  };
}
