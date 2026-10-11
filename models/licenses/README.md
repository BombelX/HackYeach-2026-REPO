# Third-party license review

Reviewed 2026-10-11. This is a repository review, not legal clearance.

## Files and provenance

- `../physnet/LICENSE`: complete, unchanged rPPG-Toolbox Responsible AI Source Code License v1.1. Applies to retained upstream contributions, including `models/physnet/physnet.py`; applicability and separate permissions for the checkpoint need confirmation.
- `../sapimouse/LICENSE`: original, unchanged SAPIMouse Apache 2.0 license, bundled with its source and models. Keep this file with distributions of that source.
- `../mediapipe/LICENSE`: standard Apache 2.0 license text. MediaPipe source uses Apache 2.0; the official blendshape model card also explicitly identifies Apache 2.0. This alone does not establish the licensing of every component in the downloaded face/pose bundles.
- `../haarcascade/LICENSE`: notice extracted verbatim (apart from outer whitespace) from `models/haarcascade/haarcascade_frontalface_default.xml`. The embedded notice remains intact.

Sources:
- https://github.com/ubicomplab/rPPG-Toolbox/blob/main/LICENSE
- https://github.com/ubicomplab/rPPG-Toolbox/blob/main/neural_methods/model/PhysNet.py
- https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE
- https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf
- https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker
- https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker

## Assessment: compliance is not established

1. PhysNet distribution requires the complete upstream license. It is retained here and linked from the source and repository README. Include `models/physnet/` when packaging the backend; shipping only `backend/` would omit the license.
2. The original PhysNet source header says research purposes only and commercial use is prohibited, despite also mentioning MIT. Preserve both notices; do not assume this is unrestricted MIT software. Written clarification from the rights holder is needed before commercial use.
3. The toolbox license restricts crime prediction, explicitly including heart-rate and facial/emotion analysis. `backend/bank24_camera_risk.py` feeds these signals into owner/pressure assessments and maps them to account-takeover/coercion risk. Whether this use falls within the restriction is unresolved. Demo/research labels and user consent do not override prohibited uses. Obtain written permission or replace/remove this component from the potentially conflicting use.
4. The toolbox license requires downstream restrictions in enforceable user/distribution agreements. No such agreement was found in the inspected application UI. This README provides notice but does not establish enforceable acceptance or satisfy that obligation by itself.
5. MediaPipe Apache distribution obligations include providing the license, retaining attribution and applicable notices, and identifying modifications. The code uses downloaded, unmodified model assets. Exact face/pose bundle terms and any additional notices still need verification; source-code licensing alone is not sufficient evidence for every weight file.
6. The Haar cascade retains its copyright, conditions and disclaimer; this folder includes a separate copy for binary packages. No endorsement was found in the inspected documentation.
7. Keystroke checkpoints and other research artifacts lack a complete per-artifact provenance/rights inventory. The Apache license for SAPIMouse code does not automatically establish rights to datasets or trained weights. No project-wide compliance certification is possible from these files alone.

No runtime behavior was changed during this review. The unresolved PhysNet use and agreement requirements must be addressed before treating distribution or deployment as cleared.
