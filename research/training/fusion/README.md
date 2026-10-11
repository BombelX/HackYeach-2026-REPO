# Multimodal fusion (`research/training/fusion/`)

A small transformer compares the current session with the account owner's profile.
It replaces `fusion_session_model.py` plus XGBoost, whose old results contained
label leakage (see below).

## Architecture

Ten-second windows with a five-second stride produce six 128D tokens plus CLS:

| Token | Input | Trainable component |
| --- | --- | --- |
| Keyboard | Frozen Conformer 128D embeddings from `keyboard_windows.parquet`, `keystroke_long_epoch_59.pt` | `Linear(128,128)` adapter |
| Mouse | 19 speed, straightness, click, pause and scroll features, plus profile differences | MLP |
| Pulse | BPM mean/std/slope, spectral concentration and crop quality from `pulse.parquet` | MLP |
| Face/posture | 52 blendshapes, four posture features from `timeline.parquet`, bbox motion/size | MLP |
| Context | Paste/copy/blur/hidden/focus, field-entry counts, RTT/jitter/latency/HTTP errors, device match, network HGB in a 64D slot | MLP and `Linear(64,128)` network adapter |
| Profile | Keyboard adapter plus MLP of enrollment mouse/pulse/face means | As above |

```text
6 tokens + CLS → TransformerEncoder (2 layers, 4 heads, d=128, ff=256, pre-norm)
               → CLS → p(not owner), p(owner under pressure)
```

The baseline has 341,202 parameters. Missing modalities use zero values and
`key_padding_mask`, rather than guessed measurements.

A profile uses the first half of that person's `calm_1` session; each person has
only one calm session in this dataset. The second half is the calm probe. The split
uses the median keyboard-window time, with no keyboard window shared across sides.

## Pairs and labels

| Session | Profile | Not owner | Pressure |
| --- | --- | --- | --- |
| Second-half calm or dictation by A | A | 0 | 0 |
| Scam by A | A | 0 | 1 |
| Intruder B on A's account | Victim A | 1 | — |
| Any B session | A, different from B | 1 | — |

Intruder sessions against the intruder's own profile are ambiguous and excluded.
Pairs are formed only within a split; each person belongs to exactly one split.

## Training

From the repository root, expose `research/` on the module path:

```bash
export PYTHONPATH="$PWD/research"
python -m training.fusion.train
python -m training.fusion.train --rebuild-cache
python -m training.fusion.train --epochs 300 --patience 60 --min-epochs 20
```

The default run uses three seeds × five folds on four GPUs, then a final model.
Rebuild the cache after changing `data/processed`.

Capacity comparisons use separate outputs without replacing the final model:

```bash
python -m training.fusion.train --variant compact --no-final \
  --output-dir research/training/artifacts/fusion/experiments/compact
python -m training.fusion.train --variant wider --no-final \
  --output-dir research/training/artifacts/fusion/experiments/wider
```

- Each fold has about eight test people, seven validation people and the remaining training people. Normalization uses training only.
- Modality dropout: pulse 0.3, face 0.3, context 0.2, mouse/keyboard 0.1.
- Pair weights balance classes and count each session once. Session output is the mean window logit.
- The alarm model uses 36 training people and five held-out people for checkpoint/threshold selection, rather than fitting all 41. Calibration must remain separate.
- Folds train independently. `best epoch 22/82` means 82 epochs ran and epoch 22 was restored. The limit is 300 with patience 60. Selection uses continuous balanced pair/session BCE after epoch 20. Early small-validation-set AUC was unstable. A fixed learning rate of 3e-4 avoids coupling the final schedule to the CV epoch limit. Do not force 300 epochs when validation worsens.
- Artifacts: `research/training/artifacts/fusion/{fusion_model.pt,cv_summary.json,cv_scores.json,train.log}`.
- The network model is a freshly trained HGB using six window features (RTT, jitter, latency, HTTP), excluding upload counts and real-participant profile features. Each fold sees training people only. Fusion training sessions receive person-grouped internal out-of-fold network predictions; validation/test use the HGB fitted on training people. The final checkpoint bundles its transformer and HGB.

## Cross-validation results

Three seeds × five folds, evaluated at session level:

| Metric | Fusion | Without context | Keyboard cosine |
| --- | --- | --- | --- |
| Not-owner AUC | 0.961 ± 0.03 | 0.718 ± 0.08 | 0.722 ± 0.12 |
| Not-owner EER | 0.077 | 0.339 | 0.355 |
| Not-owner AUC for keyboard pairs | 0.957 | 0.777 | 0.722 |
| Pressure AUC, scam vs calm/dictation | 0.792 ± 0.14 | 0.753 | — |

After checkpoint-selection changes and retraining with network HGB, not-owner AUC
was **0.972 ± 0.021**, pressure AUC **0.775 ± 0.138**; without context, 0.792 and
0.764. The protocol also changed, so this is not an isolated network-model effect.
`cv_summary.json` contains all 15 folds.

### Capacity and overfitting

The same folds/inputs compared baseline, compact (96D, dropout 0.2, weight decay
0.1) and wider (160D, dropout 0.2, weight decay 0.1). All have two layers/four heads.

| Variant | Parameters | Not-owner AUC | No-context AUC | Pressure AUC |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 341,202 | 0.972 | **0.792** | **0.775** |
| Compact | 210,866 | 0.972 | 0.752 | 0.773 |
| Wider | 504,306 | 0.973 | 0.771 | 0.751 |

A wider network did not improve pressure detection and worsened the no-context
ablation. Compact's lower validation loss does not imply better AUC. Baseline was
retained; variants did not overwrite `fusion_model.pt`. Reports are in
`artifacts/fusion/experiments/{compact,wider}/cv_summary.json` under `research/training/`.
These are exploratory results on architecture-selection folds, not an independent
test of the chosen variant. Some validation folds have very few pressure sessions;
stronger GPUs do not create more independent people or scenarios.

### Camera biometrics

The same folds compare full training with training from scratch without pulse,
face/posture or their enrollment-profile statistics. Each variant selects its
checkpoint and threshold on validation people only. A separate failure test masks
the camera only at inference in a camera-trained model.

| Variant | Not-owner AUC | Owner-pressure AUC |
| --- | ---: | ---: |
| Trained/tested with camera | **0.972 ± 0.021** | 0.775 ± 0.138 |
| Trained with camera, tested without | 0.961 ± 0.028 | 0.805 ± 0.116 |
| Trained/tested without camera | 0.961 ± 0.037 | 0.797 ± 0.115 |

The intruder AUC gain is about **0.011**, not a double-digit percentage-point
accuracy increase. Pressure showed no gain relative to fold variability. At
separately selected validation thresholds, the full model flagged 13/19, 16/19,
13/19 scam sessions across seeds; no-camera flagged 14/19, 10/19, 12/19, with
different false-alarm costs. These are the **same 19** sessions, not 57 independent
cases. Of 108 sessions, 83 had face features and 82 pulse features; missing inputs
were masked. Context still includes recorder-upload timing and device agreement,
which may indirectly reveal video presence: this is not removal of every camera
trace. There is no independent new-user validation set.

```bash
python -m training.fusion.train --no-camera --no-final \
  --output-dir research/training/artifacts/fusion/experiments/no_camera
```

Reports: `experiments/{camera_ablation_baseline,no_camera}/cv_summary.json` under
`research/training/artifacts/fusion/`. The default checkpoint was not overwritten.

### Camera without device-match features

Full CV was repeated with all nine profile/device comparison features, including
`device_known`, zeroed throughout training, validation and test. Other context
and the fold-local HGB stayed unchanged. The no-camera variant also removes
biometrics and their profile statistics during training.

| No-device-match variant | Not-owner AUC | Not-owner EER | Owner-pressure AUC |
| --- | ---: | ---: | ---: |
| With camera | **0.840 ± 0.067** | 0.241 ± 0.080 | 0.768 ± 0.123 |
| Without camera | 0.752 ± 0.120 | 0.318 ± 0.092 | **0.791 ± 0.105** |

Paired not-owner AUC increased by **0.088** with camera (12/15 folds). This supports
utility in this dataset/pair construction, not a guaranteed 8.8-point detection
gain on new devices. Pressure changed by −0.023 AUC (7/15 folds favored camera).

Validation thresholds flagged 18/19, 15/19, 16/19 scams with camera and 19/19,
18/19, 18/19 without. False alarms affected 48/62, 33/62, 42/62 normal sessions
with camera and 57/62, 46/62, 38/62 without. Again, the same 19 scams are reused.
Natural intruder/victim pairs numbered only 0, 1, 0 per seed; most intruder pairs
were synthetic. Remaining network/context features may expose device or recorder
presence. This is exploratory, not independent new-person/camera/device validation.

```bash
python -m training.fusion.train --no-device-match --no-final --gpus 0,1,2,3 \
  --output-dir research/training/artifacts/fusion/experiments/no_device_with_camera
python -m training.fusion.train --no-device-match --no-camera --no-final --gpus 0,1,2,3 \
  --output-dir research/training/artifacts/fusion/experiments/no_device_no_camera
```

Reports are under the corresponding experiment folders. `--no-final` protects the
deployed checkpoint. A new final checkpoint records `device_match_off`, which
inference respects.

### Weakened device match

Instead of removing nine device features (including `same_timezone`), this
configuration scales them by 0.25 and drops them together in 50% of training
windows. Validation/test/inference always use scale 0.25 without randomness.
Scaling alone does not limit influence because weights can compensate; dropout
regularizes reliance. The same people, seeds, folds, network model and other
context were used. This was one specified configuration, not test-tuned parameters.

| Device match | Not-owner AUC, camera | Not-owner AUC, no camera | Pressure AUC, camera | Pressure AUC, no camera |
| --- | ---: | ---: | ---: | ---: |
| Full, previous experiment | 0.972 ± 0.021 | 0.961 ± 0.037 | 0.775 ± 0.138 | 0.797 ± 0.115 |
| Weakened: scale 0.25, dropout 0.5 | **0.877 ± 0.056** | 0.854 ± 0.100 | 0.767 ± 0.138 | 0.794 ± 0.114 |
| Removed, previous experiment | 0.840 ± 0.067 | 0.752 ± 0.120 | 0.768 ± 0.123 | 0.791 ± 0.105 |

Camera improves intruder AUC by 0.023 (10/15 folds), with no pressure advantage.
Intruder EER is 0.202 with camera and 0.219 without. Validation-selected thresholds
flagged 18/19, 17/19, 16/19 scams with camera, 17/19, 15/19, 17/19 without;
normal-session alarms were 49/62, 37/62, 36/62 and 43/62, 44/62, 32/62.
Reducing device reliance substantially worsens intruder performance compared with
full matching and still produces many false alarms.

There is no IP geolocation or within-person location-change data. `same_timezone`
only compares timezones. CV does **not** measure genuine owner sign-in from a new
location/device; such scenarios need collecting. Scaling/dropout do not provide
a hard upper bound on device influence. Other network features may still expose
environment information.

```bash
python -m training.fusion.train --device-match-scale 0.25 --device-match-dropout 0.5 \
  --no-final --gpus 0,1,2,3 \
  --output-dir research/training/artifacts/fusion/experiments/weak_device_with_camera
python -m training.fusion.train --device-match-scale 0.25 --device-match-dropout 0.5 \
  --no-camera --no-final --gpus 0,1,2,3 \
  --output-dir research/training/artifacts/fusion/experiments/weak_device_no_camera
```

Reports are in those experiment folders. A subsequently trained final checkpoint
stores the scale and inference applies it automatically; the deployed checkpoint
remains unchanged.

Most not-owner performance comes from matching UA/screen/timezone. Intruders in
this dataset always use different computers. The no-context column better reflects
behavioral biometrics: about 0.78 versus 0.72 for keyboard cosine on identical pairs.
Pressure varies considerably with about eight people per fold. Treat it as a
signal, not proof. Camera BPM is experimental.

## Inference

```bash
python -m training.fusion.infer --session <session_id_or_directory> --profile <participant_code> --windows
python research/training/inference_xgb_suspicious.py --session <id> --profile <participant_code>
```

`FusionPredictor.predict(session, profile)` computes the bundled network HGB
signal. It returns `p_not_owner`, `p_pressure`, auxiliary uncalibrated
`network_signal` (mean HGB scam/intruder prediction), and window outputs.
Old checkpoints without the network model are rejected with retraining instructions.

### Optional face-manipulation signal

The independent [Deep-Fake-Detector-v2-Model](https://huggingface.co/prithivMLmods/Deep-Fake-Detector-v2-Model)
image classifier (Apache-2.0, pinned revision) evaluates at most 16 local video
frames after MediaPipe face cropping. Video is not sent to an external service;
only public weights are downloaded on first use. It changes neither fusion
outputs nor the review score/threshold, and requires no fusion retraining.

```bash
python -m pip install -r research/training/fusion/requirements-deepfake.txt
python -m training.fusion.infer --session <id> --profile <code> --deepfake
python research/training/inference_xgb_suspicious.py --session <id> --profile <code> --deepfake
python -m training.fusion.infer --session <id> --profile <code> --deepfake \
  --deepfake-video /path/to/recording.webm
```

`deepfake_assessment.status` is `scored_unvalidated` or `unavailable`, for example
`no_source_video` or `no_face_detected`. Outputs include frame count and median,
maximum and 90th percentile **frame-class scores**, not the probability a person
is a deepfake. Missing video/face or a low score is not proof of authenticity.
This image classifier detects neither replay nor liveness and is unvalidated on
these camera recordings. Real frames can score highly as fake. Without comparable
deepfake/replay recordings, no defensible threshold or false-positive/negative
rate exists. The result is for manual analysis and does not block users.

### Review alarm, not automatic blocking

`inference_xgb_suspicious.py` returns `review_score`, `review_threshold` and
`review_required`. The combined score is **not a calibrated fraud percentage**.
By default it uses the checkpoint threshold; `--threshold` explicitly overrides it.
The calibration target is at least 95% **validation** detection separately for
owner scams and intruder pairs, choosing the highest threshold satisfying both.
The output requests additional/manual review only.

Held-out test scams **did not reach 95%**: the three seeds detected 13/19, 16/19,
13/19, with normal-session false alarms 36/62, 27/62, 26/62. Synthetic intruder
pairs detected: 665/681, 643/671, 662/684. Natural intruder/victim pairs: 0, 1, 0.
Do not interpret three evaluations of the same 19 scams as 57 independent cases.
The deployed threshold is 0.1285, selected on only three scams among five
validation people; that set also selected the epoch. No 95% new-user guarantee
exists.

A post-test exploratory threshold of 0.05 detected 18–19/19 scams but referred
50–53/62 normal sessions (81–85%). Because it was chosen after viewing test
results, it is a tradeoff analysis, not an unbiased deployment result, and is not
the default. Reducing false negatives needs more independent people, scams and
natural intruder/victim attempts.

## Network-model integration

The `network_session_train.ipynb` analysis found:

- `server_request` records recorder uploads (`/face`, `/events`, `/video`, `/net`, `/api/ping`), not banking traffic.
- The notebook reads top-level `method`/`path`, but they are inside `payload_json`. Its LSTM vocabulary therefore collapses to `GET:other:na`, carrying no sequence information.
- Grouped logistic-regression AUC 0.72 relies almost entirely on `n_req` (alone 0.735): scam sessions last longer and include chat, causing more recorder requests. This is a recording artifact. RTT alone gives 0.53; intruder vs rest 0.52.
- `pressure = scam + intruder` mixes two distinct tasks.

Fusion therefore uses window-level connection quality only, excluding counts.
`net_emb[:,0]` holds HGB probability and the remaining 63 dimensions are zero;
this is not an LSTM embedding. `data/processed/models/network/network_hgb.joblib`
is **not loaded**: it was trained on all people with 51 features, including real-user
`z_*` and upload counts. Using it in CV would leak identities and labels.
`training/fusion/network.py` instead fits fold-local HGB with the same
hyperparameters on safe features and bundles a new final model in `fusion_model.pt`.
The first CV table predates this HGB; later results and current `cv_summary.json`
reflect retraining.

## Problems in the legacy implementation

- Context included post-session `stress`/`hurry`, `condition`, `group`, `meta`; mouse vectors and XGBoost also included stress/hurry. This caused stress AUC 1.0. Old `artifacts/xgboost*/` pickles are invalid for deployment.
- Profiles included the session being assessed and lacked B-versus-A pairs.
- Modality masks came from vector norms; `_numeric_from_session` averaged arbitrary columns, including timestamps.
- `pulse_windows.parquet` had null `heart_rate_bpm` throughout; current features use `pulse.parquet`.
- `chat_reply` and chat markers occur only in scams and are excluded through `LEAKY_FIELDS`.

`fusion_session_model.py` has had these leaks removed and remains for compatibility.
`inference_xgb_suspicious_legacy.py` retains original XGBoost inference for inspection.

## Mouse CatBoost and XGBoost (GUIDÆTA)

`training/mouse_boost_benchmark.py` compares identical features/pairs: task 1
provides enrollment, tasks 2–3 probes, five random intruders per probe. Train,
validation and test people are disjoint. Each of five outer folds chooses one of
four hyperparameter configurations on inner validation, refits scaling on
train+validation, trains, then evaluates test once. L1 distance is the baseline.

The original `Mouse_emmbededr.ipynb` normalized each probe against the **actual**
person's profile, even for intruder pairs, before subtracting the claimed owner's
profile. That uses true identity during inference and invalidates intruder pairs.
The corrected benchmark fits global median/IQR on training people only, then uses
`abs(z_probe - z_enroll_claimed)` against the claimed owner's task-1 median.
Do not use the old `mouse_catboost_full.cbm` without retraining.

| Mean AUC across five test folds | Seed 42 | Seed 43 |
| --- | ---: | ---: |
| L1 | 0.671 | 0.679 |
| Tuned CatBoost | **0.767** | **0.763** |
| Tuned XGBoost | 0.762 | 0.761 |

Seed-42 EER: L1 0.377, CatBoost 0.301, XGBoost 0.304. A roughly 0.003 AUC
CatBoost/XGBoost difference is too small to declare XGBoost superior. CatBoost
replaces the invalid mouse model, not fusion. This is identity verification on
GUIDÆTA (163 people), not a HackYeah result. Synthetic pairs are correlated;
their count is not the number of independent trials. Task 1 → 2/3 transfer remains
harder than reproducing the same task.

```bash
python -m training.mouse_boost_benchmark
python -m training.mouse_boost_benchmark --seed 43 \
  --output research/training/artifacts/mouse_boost/comparison_seed43.json --no-final
```

Reports, new models and scaling are in `research/training/artifacts/mouse_boost/`.
`score_mouse(probe,enrollment,kind="catboost")` accepts raw 20-feature GUIDÆTA
vectors and the claimed owner's task-1 sessions, without probe identity.
Fusion uses different 19-feature ten-second mouse windows. The GUIDÆTA classifier
cannot be inserted directly into the mouse token or its AUC cited as fusion
performance. A shared extractor or HackYeah-window retraining and a separate
participant-held-out test are required first.
