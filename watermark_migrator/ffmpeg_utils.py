import asyncio
import json
import os

from .config import Config


async def _run(cmd: list[str]) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode, out, err


async def get_duration(cfg: Config, video_path: str) -> float:
    cmd = [
        cfg.ffprobe_bin, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", video_path,
    ]
    code, out, err = await _run(cmd)
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err.decode(errors='ignore')}")
    return float(json.loads(out)["format"]["duration"])


async def get_video_dimensions(cfg: Config, video_path: str) -> tuple[int, int]:
    cmd = [
        cfg.ffprobe_bin, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", video_path,
    ]
    code, out, err = await _run(cmd)
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err.decode(errors='ignore')}")
    stream = json.loads(out)["streams"][0]
    return int(stream["width"]), int(stream["height"])


async def extract_sample_frames(cfg: Config, video_path: str, out_dir: str) -> list[str]:
    duration = await get_duration(cfg, video_path)
    fractions = [0.15, 0.5, 0.85][: cfg.sample_frames] or [0.5]
    paths = []
    for i, frac in enumerate(fractions):
        ts = max(0.0, duration * frac)
        out_path = os.path.join(out_dir, f"sample_{i}.jpg")
        cmd = [
            cfg.ffmpeg_bin, "-y", "-ss", f"{ts:.2f}", "-i", video_path,
            "-frames:v", "1", "-q:v", "2", out_path,
        ]
        code, _, err = await _run(cmd)
        if code == 0 and os.path.exists(out_path):
            paths.append(out_path)
    return paths


async def clean_watermark(
    cfg: Config, input_path: str, output_path: str, bbox: tuple[int, int, int, int]
) -> None:
    x, y, w, h = bbox

    # Pad the detected box a bit so slightly-off detection still fully covers
    # the badge (better to blur a touch more area than leave an edge of text
    # readable).
    pad = max(6, int(0.15 * max(w, h)))
    x, y = x - pad, y - pad
    w, h = w + 2 * pad, h + 2 * pad

    # Only the box itself needs to be a valid region of the frame - unlike
    # delogo, a plain blur doesn't need surrounding context pixels, so it
    # works right up against a frame edge (very common for corner badges).
    frame_w, frame_h = await get_video_dimensions(cfg, input_path)
    x = max(0, min(x, frame_w - 1))
    y = max(0, min(y, frame_h - 1))
    w = max(2, min(w, frame_w - x))
    h = max(2, min(h, frame_h - y))

    # Heavily blur just the watermark's box and paste it back over the
    # original frame - the rest of the picture is untouched pixel-for-pixel,
    # and the blurred patch makes any text in it unreadable without trying
    # (and risking failing) to reconstruct what's underneath.
    blur = (
        f"split[main][wm];"
        f"[wm]crop={w}:{h}:{x}:{y},boxblur=20:4[blurred];"
        f"[main][blurred]overlay={x}:{y}"
    )

    if cfg.use_gpu:
        # Decode on CPU (cheap relative to encode) to sidestep flaky
        # hwdownload/nvdec format negotiation across ffmpeg builds; still get
        # the GPU speedup where it matters most, on the encode side.
        vf = f"{blur},format=nv12,hwupload_cuda"
        cmd = [
            cfg.ffmpeg_bin, "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:v", "h264_nvenc", "-preset", cfg.nvenc_preset,
            "-rc", "vbr", "-cq", str(cfg.nvenc_cq),
            "-c:a", "copy",
            output_path,
        ]
    else:
        cmd = [
            cfg.ffmpeg_bin, "-y", "-i", input_path,
            "-vf", blur,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "copy",
            output_path,
        ]

    code, _, err = await _run(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg clean failed: {err.decode(errors='ignore')[-2000:]}")
