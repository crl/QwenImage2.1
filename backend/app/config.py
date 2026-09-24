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

HUNYUAN_UNET = os.environ.get("HUNYUAN_UNET", "hunyuanvideo1.5_720p_i2v_fp16.safetensors")
HUNYUAN_CLIP_1 = os.environ.get("HUNYUAN_CLIP_1", "qwen_2.5_vl_7b_fp8_scaled.safetensors")
HUNYUAN_CLIP_2 = os.environ.get("HUNYUAN_CLIP_2", "byt5_small_glyphxl_fp16.safetensors")
HUNYUAN_VAE = os.environ.get("HUNYUAN_VAE", "hunyuanvideo15_vae_fp16.safetensors")
HUNYUAN_CLIP_VISION = os.environ.get("HUNYUAN_CLIP_VISION", "sigclip_vision_patch14_384.safetensors")
# Official 720p I2V template: euler / simple / 20 steps / cfg 6 / ModelSamplingSD3 shift 7.
HUNYUAN_STEPS = 20
HUNYUAN_CFG = 6.0
HUNYUAN_SHIFT = 7.0
HUNYUAN_FPS = 24
VIDEO_DURATION_DEFAULT = 5
VIDEO_DURATION_MIN = 1
VIDEO_DURATION_MAX = 15
# Short edge and pixel cap. 720p is the I2V training size (1280×720 @16:9).
# 480p matches the node default (848×480) and is the practical size on 12GB.
VIDEO_SIZES = {
    "480p": (480, 848 * 480),
    "720p": (720, 1280 * 720),
}


def video_frame_length(seconds: int | float) -> int:
    """Seconds → HunyuanVideo 1.5 length (4k+1) at 24fps. 5s → 121 frames."""
    sec = max(VIDEO_DURATION_MIN, min(VIDEO_DURATION_MAX, int(round(float(seconds)))))
    target = max(1, round(sec * HUNYUAN_FPS))
    k = max(0, round((target - 1) / 4))
    return 4 * k + 1

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


def video_canvas(
    aspect: str,
    source_wh: tuple[int, int] | None = None,
    quality: str = "720p",
) -> tuple[int, int]:
    """HunyuanVideo 1.5 canvas for 480p or 720p. Sides are multiples of 16."""
    import math

    short_edge, max_pixels = VIDEO_SIZES.get(quality, VIDEO_SIZES["720p"])
    if aspect == "auto" and source_wh and source_wh[0] > 0 and source_wh[1] > 0:
        width, height = source_wh
    else:
        wr, hr = ASPECT_RATIOS.get(aspect, (16, 9))
        if wr >= hr:
            width, height = int(short_edge * wr / hr), short_edge
        else:
            width, height = short_edge, int(short_edge * hr / wr)
    ratio = width / max(height, 1)
    if ratio >= 1.0:
        nom_w, nom_h = short_edge * ratio, float(short_edge)
    else:
        nom_w, nom_h = float(short_edge), short_edge / ratio
    if nom_w * nom_h > max_pixels:
        scale = math.sqrt(max_pixels / (nom_w * nom_h))
        nom_w, nom_h = nom_w * scale, nom_h * scale
    return (
        max(16, round(nom_w / 16) * 16),
        max(16, round(nom_h / 16) * 16),
    )


def wrap_transparent(prompt: str) -> str:
    body = prompt.strip()
    return (
        "This is an RGBA image with transparency. "
        f"{body} "
        "The image has alpha channel and the background is transparent."
    )
