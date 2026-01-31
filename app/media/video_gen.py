import os
import math
import gc
import torch
from PIL import Image
from diffusers import LTXPipeline
from diffusers.utils import export_to_video

from app.media.ffmpeg import run

def _frames_for_seconds(seconds: int, fps: int) -> int:
    # LTX-Video tooling often expects (8 * k + 1) frames.
    # We enforce that to reduce shape/runtime errors.
    seconds = max(1, int(seconds))
    frames = max(9, seconds * fps)
    k = math.ceil((frames - 1) / 8)
    return int(k * 8 + 1)

def _round_down_multiple(x: int, m: int) -> int:
    return max(m, x - (x % m))

class VideoGen:
    _pipe = None

    def __init__(self):
        device = os.getenv("DEVICE", "cuda")
        self.device = device if (device == "cuda" and torch.cuda.is_available()) else "cpu"
        self.fps = int(os.getenv("VIDEO_FPS", "24"))

        if VideoGen._pipe is None:
            model_id = os.getenv("VIDEO_MODEL", "Lightricks/LTX-Video")

            if self.device == "cuda":
                # Prefer bfloat16 if supported; otherwise float16
                dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            else:
                dtype = torch.float32

            VideoGen._pipe = LTXPipeline.from_pretrained(model_id, torch_dtype=dtype)
            if os.getenv("ENABLE_CPU_OFFLOAD", "false").lower() == "true" and self.device == "cuda":
                # trades speed for lower VRAM
                VideoGen._pipe.enable_model_cpu_offload()
            else:
                VideoGen._pipe.to(self.device)

            VideoGen._pipe.set_progress_bar_config(disable=True)

    def _generate_clip(self, prompt: str, negative_prompt: str, width: int, height: int, seconds: int, raw_mp4: str):
        num_frames = _frames_for_seconds(seconds, self.fps)
        steps = int(os.getenv("VIDEO_INFERENCE_STEPS", "40"))
        guidance = float(os.getenv("VIDEO_GUIDANCE", "5.0"))

        g = torch.Generator(device="cuda" if self.device == "cuda" else "cpu").manual_seed(abs(hash(raw_mp4)) % (2**31))

        with torch.inference_mode():
            frames = VideoGen._pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_frames=num_frames,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=g,
            ).frames[0]

        export_to_video(frames, raw_mp4, fps=self.fps)
        # Return first frame for cover usage (as PIL)
        cover = frames[0] if frames else None

        # reduce memory pressure
        del frames
        gc.collect()
        if self.device == "cuda":
            torch.cuda.empty_cache()
        return cover

    def generate_step_video(
        self,
        shots: list[dict],
        negative_prompt: str,
        out_mp4_path: str,
        out_cover_png_path: str,
        target_seconds: int,
        work_dir: str,
    ):
        base_w = int(os.getenv("VIDEO_BASE_WIDTH", "1216"))
        base_h = int(os.getenv("VIDEO_BASE_HEIGHT", "704"))

        # Keep within common multiples for latent grids
        base_w = _round_down_multiple(base_w, 16)
        base_h = _round_down_multiple(base_h, 16)

        segment_s_default = int(os.getenv("VIDEO_SEGMENT_SECONDS", "6"))
        upscale = os.getenv("VIDEO_UPSCALE_TO_1080P", "true").lower() == "true"

        raw_parts = []
        cover_saved = False
        seconds_done = 0

        # If planner didn't supply shots, generate a single generic shot
        if not shots:
            shots = [{"duration_s": min(segment_s_default, max(1, target_seconds)), "prompt": "Instructional cooking action in a clean kitchen."}]

        for si, shot in enumerate(shots):
            shot_prompt = str(shot.get("prompt") or "").strip()
            shot_seconds = int(shot.get("duration_s") or segment_s_default)
            shot_seconds = max(1, shot_seconds)

            # If the step target is large, we can repeat segments of this shot prompt.
            remaining = max(0, target_seconds - seconds_done)
            shot_total = min(remaining if remaining else shot_seconds, shot_seconds)

            # break into segments so the model stays in its comfort zone
            segments = max(1, math.ceil(shot_total / segment_s_default))

            for seg in range(segments):
                seg_seconds = min(segment_s_default, shot_total - seg * segment_s_default)
                if seg_seconds <= 0:
                    continue

                raw_mp4 = os.path.join(work_dir, f"shot{si}_seg{seg}_raw.mp4")
                try:
                    cover = self._generate_clip(
                        prompt=shot_prompt,
                        negative_prompt=negative_prompt,
                        width=base_w,
                        height=base_h,
                        seconds=seg_seconds,
                        raw_mp4=raw_mp4,
                    )
                except Exception:
                    # fallback resolution if base fails
                    raw_mp4 = os.path.join(work_dir, f"shot{si}_seg{seg}_raw_fallback.mp4")
                    cover = self._generate_clip(
                        prompt=shot_prompt,
                        negative_prompt=negative_prompt,
                        width=704,
                        height=480,
                        seconds=seg_seconds,
                        raw_mp4=raw_mp4,
                    )

                if cover is not None and not cover_saved:
                    # cover may be PIL.Image or array; ensure PIL
                    if not isinstance(cover, Image.Image):
                        cover = Image.fromarray(cover)
                    cover.save(out_cover_png_path, format="PNG")
                    cover_saved = True

                raw_parts.append(raw_mp4)
                seconds_done += seg_seconds

                if seconds_done >= target_seconds:
                    break

            if seconds_done >= target_seconds:
                break

        # Concatenate parts (no re-encoding yet)
        if len(raw_parts) == 1:
            concat_in = raw_parts[0]
        else:
            concat_list = os.path.join(work_dir, "concat.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                for p in raw_parts:
                    f.write(f"file '{p}'\n")
            concat_in = os.path.join(work_dir, "concat_raw.mp4")
            run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", concat_in])

        # Final encode: 1080p, no audio
        if upscale:
            vf = "scale=1920:1080:flags=lanczos"
        else:
            vf = "null"

        run([
            "ffmpeg", "-y",
            "-i", concat_in,
            "-vf", vf,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            out_mp4_path
        ])
