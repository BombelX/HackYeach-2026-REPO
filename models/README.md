# Model assets

This directory stores the camera-analysis assets and the keystroke checkpoints
that were located at the workspace root.

- `keystroke/baseline/` — epochs 0–19 from the baseline run.
- `keystroke/constant-lr/` — epochs 0–19 from the constant-learning-rate run.
- `keystroke/long-run/` — epochs 0–59 from the long training run.

The checkpoint files are not byte-identical, including files with the same epoch
number in different runs, so all are retained. `training/` contains the other
trained artifacts; `rPPG-Toolbox/final_model_release/` and
`research/sapimouse/TRAINED_MODELS/` contain their respective released weights.

All binary model formats are managed by Git LFS via the repository-level
`.gitattributes` file.
