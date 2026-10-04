# Camera model assets

`haarcascade_frontalface_default.xml` is OpenCV's frontal face detector from tag
4.12.0: https://github.com/opencv/opencv/blob/4.12.0/data/haarcascades/haarcascade_frontalface_default.xml.
Its Intel/OpenCV redistribution license is preserved in the XML header. It is a
fallback for OpenCV distributions that omit their `cv2/data` cascade assets.

Existing `face_landmarker.task`, `pose_landmarker_lite.task`, and
`emotion-ferplus-8.onnx` predate the Bank24 frontend implementation.

The checkout does not contain PhysNet source and weights in `rPPG-Toolbox/`.
Use `webrtc_server.py --preview-only` until those dependencies are restored;
never display invented BPM values as an actual measurement.
