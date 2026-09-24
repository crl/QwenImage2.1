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


def build_hunyuan_video(
    prompt: str,
    *,
    width: int,
    height: int,
    seed: int,
    first_frame_name: str | None = None,
    length: int = 121,
    steps: int = 20,
) -> dict[str, Any]:
    """HunyuanVideo 1.5 720p graph. Skips the template's 1080p super-resolution stage."""
    from .config import (
        HUNYUAN_CFG,
        HUNYUAN_CLIP_1,
        HUNYUAN_CLIP_2,
        HUNYUAN_CLIP_VISION,
        HUNYUAN_FPS,
        HUNYUAN_SHIFT,
        HUNYUAN_UNET,
        HUNYUAN_VAE,
    )

    graph: dict[str, Any] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": HUNYUAN_UNET, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": HUNYUAN_CLIP_1,
                "clip_name2": HUNYUAN_CLIP_2,
                "type": "hunyuan_video_15",
                "device": "default",
            },
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": HUNYUAN_VAE}},
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": prompt},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": ""},
        },
        "6": {
            "class_type": "HunyuanVideo15ImageToVideo",
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "vae": ["3", 0],
                "width": width,
                "height": height,
                "length": length,
                "batch_size": 1,
            },
        },
        "7": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["1", 0], "shift": HUNYUAN_SHIFT},
        },
        "8": {
            "class_type": "CFGGuider",
            "inputs": {
                "model": ["7", 0],
                "positive": ["6", 0],
                "negative": ["6", 1],
                "cfg": HUNYUAN_CFG,
            },
        },
        "9": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler"},
        },
        "10": {
            "class_type": "BasicScheduler",
            "inputs": {
                "model": ["1", 0],
                "scheduler": "simple",
                "steps": steps,
                "denoise": 1.0,
            },
        },
        "11": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["16", 0],
                "guider": ["8", 0],
                "sampler": ["9", 0],
                "sigmas": ["10", 0],
                "latent_image": ["6", 2],
            },
        },
        "12": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["11", 0], "vae": ["3", 0]},
        },
        "14": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["12", 0],
                "fps": float(HUNYUAN_FPS),
            },
        },
        "15": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["14", 0],
                "filename_prefix": "QwenStudioVideo",
                "format": "auto",
                "format.codec": "auto",
            },
        },
        "16": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": seed},
        },
    }
    if first_frame_name:
        graph["20"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
        graph["21"] = {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": HUNYUAN_CLIP_VISION},
        }
        graph["22"] = {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["21", 0], "image": ["20", 0], "crop": "center"},
        }
        graph["6"]["inputs"]["start_image"] = ["20", 0]
        graph["6"]["inputs"]["clip_vision_output"] = ["22", 0]
    return graph
