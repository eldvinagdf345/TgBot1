import asyncio
import json
import logging
import os

from .config import Config

logger = logging.getLogger("watermark_migrator")


async def _run(cmd: list[str]) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode, out, err


async def encode_with_fallback(
    cfg: Config, input_args: list[str], base_graph: str, output_path: str
) -> None:
    """base_graph is a filter_complex graph whose final video output is
    labeled [masked]. Tries NVENC first if cfg.use_gpu, and automatically
    falls back to libx264 on CPU if that fails - e.g. an NVIDIA driver too
    old for this ffmpeg build's NVENC version (a common, confusing failure
    that otherwise looks like the whole tool is broken)."""
    if cfg.use_gpu:
        gpu_graph = f"{base_graph};[masked]format=nv12,hwupload_cuda[outv]"
        cmd = [
            cfg.ffmpeg_bin, "-y", *input_args,
            "-filter_complex", gpu_graph, "-map", "[outv]", "-map", "0:a?",
            "-c:v", "h264_nvenc", "-preset", cfg.nvenc_preset,
            "-rc", "vbr", "-cq", str(cfg.nvenc_cq),
            "-c:a", "copy", output_path,
        ]
        code, _, err = await _run(cmd)
        if code == 0:
            return
        logger.warning(
            "GPU encode failed, falling back to CPU: %s",
            err.decode(errors="ignore").strip()[-300:],
        )

    cmd = [
        cfg.ffmpeg_bin, "-y", *input_args,
        "-filter_complex", base_graph, "-map", "[masked]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy", output_path,
    ]
    code, _, err = await _run(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode(errors='ignore')[-2000:]}")


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
    # scale/pad (used when OVERLAY_IMAGE is set) need even dimensions,
    # otherwise libswscale's rounding can make the scaled output 1px larger
    # than the pad target and ffmpeg refuses with "Padded dimensions cannot
    # be smaller than input dimensions".
    w -= w % 2
    h -= h % 2
    w, h = max(2, w), max(2, h)

    # Heavily blur just the watermark's box and paste it back over the
    # original frame - the rest of the picture is untouched pixel-for-pixel,
    # and the blurred patch makes any text in it unreadable without trying
    # (and risking failing) to reconstruct what's underneath. Everything
    # else (filler text, or a replacement badge image) is stamped on top.
    blur_graph = (
        f"[0:v]split[main][wm];"
        f"[wm]crop={w}:{h}:{x}:{y},boxblur=20:4[blurred];"
        f"[main][blurred]overlay={x}:{y}[base]"
    )

    extra_inputs: list[str] = []
    if cfg.overlay_image:
        # Stamp a fixed replacement badge (e.g. your own logo) scaled to the
        # detected watermark's size, in the same spot.
        extra_inputs = ["-i", cfg.overlay_image]
        # Preserve the overlay's own aspect ratio (shrink to fit inside the
        # box, pad the rest transparently) instead of stretching it to
        # exactly w:h, so a square/round sticker doesn't get squashed into
        # an elongated watermark box.
        graph = (
            f"{blur_graph};"
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000[badge];"
            f"[base][badge]overlay={x}:{y}[masked]"
        )
    else:
        # Stamp two rows of filler symbols at the configured color/opacity.
        fontsize = max(10, int(h / 2.6))
        row_gap = 2
        row1_y = y + max(2, (h - 2 * fontsize - row_gap) // 2)
        row2_y = row1_y + fontsize + row_gap
        text = (
            cfg.mask_text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
            .replace("%", "%%")
        )
        fontfile_arg = f"fontfile='{cfg.font_file}':" if cfg.font_file else ""
        color_spec = f"{cfg.font_color}@{cfg.font_opacity}"

        def _drawtext(label_in: str, label_out: str, row_y: int) -> str:
            return (
                f"[{label_in}]drawtext={fontfile_arg}text='{text}':"
                f"x={x + 4}:y={row_y}:fontsize={fontsize}:fontcolor={color_spec}[{label_out}]"
            )

        graph = (
            f"{blur_graph};"
            f"{_drawtext('base', 't1', row1_y)};"
            f"{_drawtext('t1', 'masked', row2_y)}"
        )

    await encode_with_fallback(cfg, ["-i", input_path, *extra_inputs], graph, output_path)
