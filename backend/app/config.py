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
}


def ensure_dirs() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def pixel_size(aspect: str, quality: str) -> tuple[int, int]:
    wr, hr = ASPECT_RATIOS.get(aspect, (1, 1))
    megapixels = 2048 * 2048 if quality == "2k" else 1024 * 1024
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
