import cv2
import numpy as np

from .config import Config


def _load_gray(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    return img


def detect_watermark(
    cfg: Config, frame_paths: list[str], template_path: str
) -> tuple[int, int, int, int] | None:
    """
    Multi-scale template matching across sample frames.
    Returns (x, y, w, h) of the best match if its score clears the
    configured threshold, otherwise None (video treated as watermark-free).
    """
    template = _load_gray(template_path)
    tpl_h, tpl_w = template.shape[:2]

    scales = np.linspace(cfg.scale_min, cfg.scale_max, cfg.scale_steps)
    best_score = -1.0
    best_bbox = None

    for frame_path in frame_paths:
        frame = _load_gray(frame_path)
        frame_h, frame_w = frame.shape[:2]

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
