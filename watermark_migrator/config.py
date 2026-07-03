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
    watermark_template: str
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


def load_config() -> Config:
    return Config(
        api_id=int(os.environ["API_ID"]),
        api_hash=os.environ["API_HASH"],
        session_name=os.environ.get("SESSION_NAME", "watermark_migrator"),
        source_channel=os.environ["SOURCE_CHANNEL"],
        target_channel=os.environ["TARGET_CHANNEL"],
        watermark_template=os.environ.get(
            "WATERMARK_TEMPLATE", "watermark_migrator/templates/watermark.png"
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
    )
