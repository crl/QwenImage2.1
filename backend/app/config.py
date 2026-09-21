from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "app.db"

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")

UNET_NAME = os.environ.get("QWEN_UNET", "qwen_image_2.1_int8_convrot.safetensors")
CLIP_NAME = os.environ.get("QWEN_CLIP", "qwen3vl_8b_int8_convrot.safetensors")
VAE_NAME = os.environ.get("QWEN_VAE", "qwen_image_2.1_vae_bf16.safetensors")

DEFAULT_STEPS = 25
DEFAULT_CFG = 1.0
DEFAULT_SAMPLER = "euler"
DEFAULT_SCHEDULER = "simple"

ASPECT_RATIOS = {
    "1:1": (1, 1),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "3:2": (3, 2),
    "2:3": (2, 3),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:5": (4, 5),
    "5:4": (5, 4),
    "21:9": (21, 9),
}

QUALITY_BASE = {
    "1k": 1024,
    "2k": 2048,
    "4k": 3840,
}


def ensure_dirs() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def pixel_size(
    aspect: str,
    quality: str,
    source_wh: tuple[int, int] | None = None,
) -> tuple[int, int]:
    if aspect == "auto" and source_wh and source_wh[0] > 0 and source_wh[1] > 0:
        wr, hr = source_wh
    else:
        wr, hr = ASPECT_RATIOS.get(aspect, (1, 1))
    base = QUALITY_BASE.get(quality, 1024)
    megapixels = base * base
    width = round(((megapixels * wr / hr) ** 0.5) / 32) * 32
    height = round(((megapixels * hr / wr) ** 0.5) / 32) * 32
    return max(32, width), max(32, height)


def wrap_transparent(prompt: str) -> str:
    body = prompt.strip()
    return (
        "This is an RGBA image with transparency. "
        f"{body} "
        "The image has alpha channel and the background is transparent."
    )
