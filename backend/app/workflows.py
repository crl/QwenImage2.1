from __future__ import annotations

from typing import Any

from .config import (
    CLIP_NAME,
    DEFAULT_CFG,
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    DEFAULT_STEPS,
    UNET_NAME,
    VAE_NAME,
)


def _loaders() -> dict[str, Any]:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": UNET_NAME, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": CLIP_NAME, "type": "qwen_image"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": VAE_NAME},
        },
        "4": {
            "class_type": "QwenImage21Cache",
            "inputs": {"model": ["1", 0], "device": "auto", "dtype": "int8"},
        },
    }


def build_t2i(
    prompt: str,
    *,
    width: int,
    height: int,
    seed: int,
    steps: int = DEFAULT_STEPS,
    negative_prompt: str = "",
) -> dict[str, Any]:
    graph = _loaders()
    graph.update(
        {
            "5": {
                "class_type": "TextEncodeQwenImage21",
                "inputs": {
                    "clip": ["2", 0],
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "resolution": min(width, height),
                    "vae": ["3", 0],
                },
            },
            "6": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "7": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["4", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": DEFAULT_CFG,
                    "sampler_name": DEFAULT_SAMPLER,
                    "scheduler": DEFAULT_SCHEDULER,
                    "positive": ["5", 0],
                    "negative": ["5", 1],
                    "latent_image": ["6", 0],
                    "denoise": 1.0,
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"images": ["8", 0], "filename_prefix": "QwenStudio"},
            },
        }
    )
    return graph


def build_edit(
    prompt: str,
    image_names: list[str],
    *,
    seed: int,
    steps: int = DEFAULT_STEPS,
    resolution: int = 1024,
    negative_prompt: str = "",
) -> dict[str, Any]:
    if not image_names:
        raise ValueError("编辑模式至少需要一张参考图")
    graph = _loaders()
    encode_inputs: dict[str, Any] = {
        "clip": ["2", 0],
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "resolution": resolution,
        "vae": ["3", 0],
    }
    for index, name in enumerate(image_names[:10], start=1):
        node_id = str(20 + index)
        graph[node_id] = {
            "class_type": "LoadImage",
            "inputs": {"image": name},
        }
        encode_inputs[f"images.image_{index}"] = [node_id, 0]
    graph["5"] = {"class_type": "TextEncodeQwenImage21", "inputs": encode_inputs}
    graph["7"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["4", 0],
            "seed": seed,
            "steps": steps,
            "cfg": DEFAULT_CFG,
            "sampler_name": DEFAULT_SAMPLER,
            "scheduler": DEFAULT_SCHEDULER,
            "positive": ["5", 0],
            "negative": ["5", 1],
            "latent_image": ["5", 2],
            "denoise": 1.0,
        },
    }
    graph["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
    }
    graph["9"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["8", 0], "filename_prefix": "QwenStudioEdit"},
    }
    return graph


def build_masked_edit(
    prompt: str,
    *,
    vision_name: str,
    original_name: str,
    mask_name: str,
    seed: int,
    steps: int = DEFAULT_STEPS,
    resolution: int = 0,
    negative_prompt: str = "",
) -> dict[str, Any]:
    graph = _loaders()
    graph["20"] = {"class_type": "LoadImage", "inputs": {"image": original_name}}
    graph["21"] = {"class_type": "LoadImage", "inputs": {"image": vision_name}}
    graph["22"] = {
        "class_type": "LoadImageMask",
        "inputs": {"image": mask_name, "channel": "red"},
    }
    graph["5"] = {
        "class_type": "TextEncodeQwenImage21",
        "inputs": {
            "clip": ["2", 0],
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "resolution": resolution,
            "vae": ["3", 0],
            "images.image_1": ["21", 0],
        },
    }
    graph["7"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["4", 0],
            "seed": seed,
            "steps": steps,
            "cfg": DEFAULT_CFG,
            "sampler_name": DEFAULT_SAMPLER,
            "scheduler": DEFAULT_SCHEDULER,
            "positive": ["5", 0],
            "negative": ["5", 1],
            "latent_image": ["5", 2],
            "denoise": 1.0,
        },
    }
    graph["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
    }
    graph["10"] = {
        "class_type": "ImageCompositeMasked",
        "inputs": {
            "destination": ["20", 0],
            "source": ["8", 0],
            "x": 0,
            "y": 0,
            "resize_source": True,
            "mask": ["22", 0],
        },
    }
    graph["9"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["10", 0], "filename_prefix": "QwenStudioEdit"},
    }
    return graph


def build_outpaint_edit(
    prompt: str,
    *,
    original_name: str,
    canvas_name: str,
    mask_name: str,
    seed: int,
    paste_x: int,
    paste_y: int,
    steps: int = DEFAULT_STEPS,
    negative_prompt: str = "",
) -> dict[str, Any]:
    graph = _loaders()
    graph["20"] = {"class_type": "LoadImage", "inputs": {"image": original_name}}
    graph["21"] = {"class_type": "LoadImage", "inputs": {"image": canvas_name}}
    graph["22"] = {
        "class_type": "LoadImageMask",
        "inputs": {"image": mask_name, "channel": "red"},
    }
    graph["5"] = {
        "class_type": "TextEncodeQwenImage21",
        "inputs": {
            "clip": ["2", 0],
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "resolution": 0,
            "vae": ["3", 0],
            "images.image_1": ["20", 0],
        },
    }
    graph["15"] = {
        "class_type": "TextEncodeQwenImage21",
        "inputs": {
            "clip": ["2", 0],
            "prompt": "",
            "negative_prompt": "",
            "resolution": 0,
            "images.image_1": ["21", 0],
        },
    }
    graph["7"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["4", 0],
            "seed": seed,
            "steps": steps,
            "cfg": DEFAULT_CFG,
            "sampler_name": DEFAULT_SAMPLER,
            "scheduler": DEFAULT_SCHEDULER,
            "positive": ["5", 0],
            "negative": ["5", 1],
            "latent_image": ["15", 2],
            "denoise": 1.0,
        },
    }
    graph["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
    }
    graph["10"] = {
        "class_type": "ImageCompositeMasked",
        "inputs": {
            "destination": ["8", 0],
            "source": ["20", 0],
            "x": paste_x,
            "y": paste_y,
            "resize_source": False,
            "mask": ["22", 0],
        },
    }
    graph["9"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["10", 0], "filename_prefix": "QwenStudioOutpaint"},
    }
    return graph


SEEDVR2_UNET = "seedvr2_7b_int8_convrot.safetensors"
SEEDVR2_VAE = "seedvr2_ema_vae_fp16.safetensors"


def build_seedvr2_upscale(
    image_name: str,
    *,
    seed: int,
    multiplier: float,
) -> dict[str, Any]:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {
            "class_type": "JoinImageWithAlpha",
            "inputs": {"image": ["1", 0], "alpha": ["1", 1]},
        },
        "3": {
            "class_type": "ResizeImageMaskNode",
            "inputs": {
                "input": ["2", 0],
                "resize_type": "scale by multiplier",
                "resize_type.multiplier": multiplier,
                "scale_method": "lanczos",
            },
        },
        "4": {
            "class_type": "SeedVR2Preprocess",
            "inputs": {"resized_images": ["3", 0]},
        },
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": SEEDVR2_VAE}},
        "6": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": SEEDVR2_UNET, "weight_dtype": "default"},
        },
        "7": {
            "class_type": "VAEEncodeTiled",
            "inputs": {
                "pixels": ["4", 0],
                "vae": ["5", 0],
                "tile_size": 512,
                "overlap": 128,
                "temporal_size": 4096,
                "temporal_overlap": 8,
            },
        },
        "8": {
            "class_type": "SeedVR2Conditioning",
            "inputs": {"model": ["6", 0], "vae_conditioning": ["7", 0]},
        },
        "9": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["6", 0],
                "seed": seed,
                "steps": 1,
                "cfg": 1,
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["8", 0],
                "negative": ["8", 1],
                "latent_image": ["7", 0],
                "denoise": 1,
            },
        },
        "10": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["9", 0],
                "vae": ["5", 0],
                "tile_size": 512,
                "overlap": 128,
                "temporal_size": 4096,
                "temporal_overlap": 8,
            },
        },
        "11": {
            "class_type": "SeedVR2PostProcessing",
            "inputs": {
                "images": ["10", 0],
                "original_resized_images": ["3", 0],
                "color_correction_method": "none",
            },
        },
        "12": {
            "class_type": "SaveImage",
            "inputs": {"images": ["11", 0], "filename_prefix": "QwenStudioUpscale"},
        },
    }
