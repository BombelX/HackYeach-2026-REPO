from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

LANDMARK_IDS = (
    10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 2, 234, 93, 132, 58, 172, 136,
    150, 149, 176, 148, 152, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
    61, 291, 13, 14, 78, 308, 33, 263, 133, 362,
)
EYE_IDS = (33, 263)
BLENDSHAPE_WEIGHT = 0.25


def face_feature(row: dict[str, Any], blendshape_names: tuple[str, ...]) -> np.ndarray | None:
    points = row.get("face_key")
    blendshapes = row.get("blendshapes")
    if not isinstance(points, list) or not isinstance(blendshapes, dict):
        return None
    by_id = {point.get("i"): point for point in points if isinstance(point, dict)}
    if any(index not in by_id for index in LANDMARK_IDS):
        return None
    xyz = np.asarray([[by_id[index].get(axis) for axis in ("x", "y", "z")]
                      for index in LANDMARK_IDS], dtype=np.float64)
    if xyz.shape != (len(LANDMARK_IDS), 3) or not np.isfinite(xyz).all():
        return None
    id_to_pos = {index: i for i, index in enumerate(LANDMARK_IDS)}
    left, right = (xyz[id_to_pos[index]] for index in EYE_IDS)
    eye_axis = right[:2] - left[:2]
    scale = float(np.linalg.norm(eye_axis))
    if scale < 1e-5:
        return None
    angle = np.arctan2(eye_axis[1], eye_axis[0])
    c, s = np.cos(angle), np.sin(angle)
    rotation = np.asarray([[c, s], [-s, c]])
    origin = (left + right) / 2
    xy = (xyz[:, :2] - origin[:2]) @ rotation.T / scale
    z = (xyz[:, 2] - origin[2:3]) / scale
    geometry = np.column_stack((xy, z)).reshape(-1)
    expression = np.asarray([blendshapes.get(name, 0.0) for name in blendshape_names], dtype=np.float64)
    if not np.isfinite(expression).all():
        return None
    vector = np.concatenate((geometry, BLENDSHAPE_WEIGHT * expression))
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm < 1e-8:
        return None
    return (vector / norm).astype(np.float32)


def load_face_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected object in {path}:{line_number}")
            rows.append(row)
    return rows


def extract_session_features(path: Path, blendshape_names: tuple[str, ...]) -> np.ndarray:
    vectors = [face_feature(row, blendshape_names) for row in load_face_rows(path)]
    return np.stack([vector for vector in vectors if vector is not None]) if any(
        vector is not None for vector in vectors) else np.empty((0, len(LANDMARK_IDS) * 3 + len(blendshape_names)),
                                                                dtype=np.float32)


def cosine_scores(vectors: np.ndarray, profile: np.ndarray) -> np.ndarray:
    values = np.asarray(vectors, dtype=np.float32)
    reference = np.asarray(profile, dtype=np.float32)
    if values.ndim != 2 or reference.ndim != 1 or values.shape[1] != reference.shape[0]:
        raise ValueError("Face vectors and profile dimensions do not match")
    reference_norm = float(np.linalg.norm(reference))
    if reference_norm < 1e-8:
        raise ValueError("Face profile is an empty vector")
    row_norms = np.linalg.norm(values, axis=1)
    valid = row_norms > 1e-8
    scores = np.full(len(values), np.nan, dtype=np.float32)
    scores[valid] = values[valid] @ (reference / reference_norm) / row_norms[valid]
    return scores


def make_unit_profile(vectors: np.ndarray) -> np.ndarray:
    if vectors.ndim != 2 or not len(vectors):
        raise ValueError("At least one valid face feature vector is required")
    mean = np.mean(vectors, axis=0, dtype=np.float64)
    norm = float(np.linalg.norm(mean))
    if norm < 1e-8 or not np.isfinite(norm):
        raise ValueError("Could not build a finite face profile")
    return (mean / norm).astype(np.float32)
