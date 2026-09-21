# Qwen Image Studio

本地对话式生图工具，界面参考 ChatGPT Images。后端把对话请求转成 ComfyUI 0.37 的 Qwen-Image-2.1 工作流，使用你已经下载的 int8 权重。

## 准备

1. 打开 **Comfy Desktop**，确认 `http://127.0.0.1:8188` 可访问。
2. 模型应能被 ComfyUI 看到（当前通过 `ComfyUI-Shared\models` 指向 `F:\ComfyUI_Models\models`）：
   - `diffusion_models/qwen_image_2.1_int8_convrot.safetensors`
   - `text_encoders/qwen3vl_8b_int8_convrot.safetensors`
   - `vae/qwen_image_2.1_vae_bf16.safetensors`

## 启动

```powershell
cd F:\Works\QwenImage2.1
.\start.ps1
```

浏览器打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。

也可分别启动：

```powershell
backend\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --app-dir backend
cd frontend
npm run dev
```

## 用法

- 首页输入描述即可文生图；生成图会进入图库。
- 同一对话里继续说话，会以上一张图为参考进行编辑。
- 可上传最多 10 张参考图。
- 「透明底」会套用官方 RGBA prompt，并保存 PNG。
- 默认 1K（约 1024²），适合 RTX 5070 12GB；2K 可能显存不足。
- 采样：euler / simple / CFG 1 / 25 steps。

会话和图保存在 `data/`。
