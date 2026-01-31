import os
import torch
from diffusers import StableDiffusionXLPipeline

class ImageGen:
    _pipe = None

    def __init__(self):
        device = os.getenv("DEVICE", "cuda")
        self.device = device if (device == "cuda" and torch.cuda.is_available()) else "cpu"

        if ImageGen._pipe is None:
            dtype = torch.float16 if self.device == "cuda" else torch.float32
            model_id = os.getenv("SDXL_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
            ImageGen._pipe = StableDiffusionXLPipeline.from_pretrained(
                model_id,
                torch_dtype=dtype,
                variant="fp16" if self.device == "cuda" else None,
            )
            ImageGen._pipe.to(self.device)
            ImageGen._pipe.set_progress_bar_config(disable=True)

    def generate_png(self, prompt: str, negative_prompt: str, out_path: str):
        width = int(os.getenv("IMAGE_WIDTH", "1024"))
        height = int(os.getenv("IMAGE_HEIGHT", "1024"))
        steps = int(os.getenv("IMAGE_STEPS", "30"))
        guidance = float(os.getenv("IMAGE_GUIDANCE", "6.5"))

        g = torch.Generator(device=self.device).manual_seed(abs(hash(out_path)) % (2**31))

        with torch.inference_mode():
            img = ImageGen._pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=g,
            ).images[0]

        img.save(out_path, format="PNG")
        if self.device == "cuda":
            torch.cuda.empty_cache()
