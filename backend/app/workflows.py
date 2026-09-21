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
