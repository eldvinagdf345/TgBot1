import glob
import os

import cv2
import numpy as np

from .config import Config

_CLAHE = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

_TEMPLATE_EXTS = ("*.png", "*.jpg", "*.jpeg")


def _load_enhanced(path: str) -> np.ndarray:
    """Grayscale + CLAHE contrast boost, so faint/near-blended watermarks
    still stand out enough for template matching to lock onto their edges."""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    return _CLAHE.apply(img)


def _load_templates(templates_dir: str) -> list[np.ndarray]:
    paths = []
    for pattern in _TEMPLATE_EXTS:
        paths.extend(glob.glob(os.path.join(templates_dir, pattern)))
    if not paths:
        raise ValueError(f"No template images found in {templates_dir}")
    return [_load_enhanced(p) for p in sorted(paths)]


def detect_watermark(
    cfg: Config, frame_paths: list[str], templates_dir: str
) -> tuple[int, int, int, int] | None:
    """
    Multi-template, multi-scale template matching across sample frames.
    Every reference image in templates_dir is tried at every scale in
    [scale_min, scale_max] against every sample frame; the single best-scoring
    match wins. Returns (x, y, w, h) if its score clears match_threshold,
    otherwise None (video treated as watermark-free).
    """
    templates = _load_templates(templates_dir)
    scales = np.linspace(cfg.scale_min, cfg.scale_max, cfg.scale_steps)

    best_score = -1.0
    best_bbox = None

    for frame_path in frame_paths:
        frame = _load_enhanced(frame_path)
        frame_h, frame_w = frame.shape[:2]

        for template in templates:
            tpl_h, tpl_w = template.shape[:2]
            for scale in scales:
                w = int(tpl_w * scale)
                h = int(tpl_h * scale)
                if w < 8 or h < 8 or w > frame_w or h > frame_h:
                    continue
                resized_tpl = cv2.resize(template, (w, h), interpolation=cv2.INTER_AREA)
                result = cv2.matchTemplate(frame, resized_tpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val > best_score:
                    best_score = max_val
                    best_bbox = (max_loc[0], max_loc[1], w, h)

    if best_score >= cfg.match_threshold:
        return best_bbox
    return None
