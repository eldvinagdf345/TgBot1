import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    api_id: int
    api_hash: str
    session_name: str
    source_channel: str
    target_channel: str
    watermark_templates_dir: str
    brand_terms_path: str
    work_dir: str
    db_path: str
    match_threshold: float
    scale_min: float
    scale_max: float
    scale_steps: int
    sample_frames: int
    use_gpu: bool
    ffmpeg_bin: str
    ffprobe_bin: str
    concurrency: int
    nvenc_preset: str
    nvenc_cq: int
    mask_text: str
    font_file: str
    font_color: str
    font_opacity: float
    overlay_image: str


def load_config() -> Config:
    return Config(
        api_id=int(os.environ["API_ID"]),
        api_hash=os.environ["API_HASH"],
        session_name=os.environ.get("SESSION_NAME", "watermark_migrator"),
        source_channel=os.environ.get("SOURCE_CHANNEL", ""),
        target_channel=os.environ.get("TARGET_CHANNEL", ""),
        watermark_templates_dir=os.environ.get(
            "WATERMARK_TEMPLATES_DIR", "watermark_migrator/templates"
        ),
        brand_terms_path=os.environ.get(
            "BRAND_TERMS_PATH", "watermark_migrator/brand_terms.txt"
        ),
        work_dir=os.environ.get("WORK_DIR", "watermark_migrator/work"),
        db_path=os.environ.get("DB_PATH", "watermark_migrator/state.sqlite3"),
        match_threshold=float(os.environ.get("MATCH_THRESHOLD", "0.7")),
        scale_min=float(os.environ.get("SCALE_MIN", "0.5")),
        scale_max=float(os.environ.get("SCALE_MAX", "2.5")),
        scale_steps=int(os.environ.get("SCALE_STEPS", "25")),
        sample_frames=int(os.environ.get("SAMPLE_FRAMES", "3")),
        use_gpu=os.environ.get("USE_GPU", "1") == "1",
        ffmpeg_bin=os.environ.get("FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=os.environ.get("FFPROBE_BIN", "ffprobe"),
        concurrency=int(os.environ.get("CONCURRENCY", "2")),
        nvenc_preset=os.environ.get("NVENC_PRESET", "p4"),
        nvenc_cq=int(os.environ.get("NVENC_CQ", "19")),
        mask_text=os.environ.get("MASK_TEXT", "@#&@#%"),
        font_file=os.environ.get("FONT_FILE", ""),
        font_color=os.environ.get("FONT_COLOR", "white"),
        font_opacity=float(os.environ.get("FONT_OPACITY", "0.85")),
        overlay_image=os.environ.get("OVERLAY_IMAGE", ""),
    )


def prompt_for_channels(cfg: Config) -> None:
    """Ask for source/target channel at startup; press Enter to keep
    whatever is already in .env instead of typing it every time."""
    src = input(f"Канал-источник [{cfg.source_channel or 'не задан'}]: ").strip()
    if src:
        cfg.source_channel = src
    if not cfg.source_channel:
        raise SystemExit("Канал-источник не указан.")

    tgt = input(f"Канал-приёмник [{cfg.target_channel or 'не задан'}]: ").strip()
    if tgt:
        cfg.target_channel = tgt
    if not cfg.target_channel:
        raise SystemExit("Канал-приёмник не указан.")
