import os
import shutil
import tempfile
import gc
import traceback
from typing import Dict, Any, List

from app.media.step_rewriter import rewrite_steps
from app.media.planner import plan_recipe_media
from app.media.image_gen import ImageGen
from app.media.video_gen import VideoGen
from app.media.ffmpeg import run as ffmpeg_run

from app.progress import ensure_dirs, init_manifest, save_manifest, mark_item


def _exists(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0


def _extract_cover_from_video(video_path: str, cover_path: str) -> None:
    # Fast fallback: extract first frame as PNG (no SDXL re-run)
    ffmpeg_run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "select=eq(n\,0)",
        "-vframes", "1",
        cover_path
    ])


def generate_assets_job(recipe: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate recipe assets.

    Resumability:
    - Outputs are written deterministically to:
      {ASSETS_BASE_DIR}/{id}/ingredients/{i}.png and {ASSETS_BASE_DIR}/{id}/steps/{i}.(png|mp4)
    - A manifest.json is checkpointed frequently.
    - If this job fails, simply POST the same payload again with the same id.
      The worker will SKIP already generated files and continue from the first missing asset.

    Notes:
    - Resume is at the *asset level* (per ingredient / per step). A partially generated step video
      is regenerated for that step if the final mp4 is missing.
    """
    recipe_id = int(recipe["id"])
    ingredients: List[str] = recipe.get("ingredients", []) or []
    steps: List[str] = recipe.get("recipe_steps") or recipe.get("cooking_steps") or []

    base_dir = os.getenv("ASSETS_BASE_DIR", "/data/assets")
    dirs = ensure_dirs(base_dir, recipe_id)
    out_dir = dirs["root"]
    ing_dir = dirs["ingredients"]
    step_dir = dirs["steps"]

    manifest = init_manifest(base_dir, recipe)
    save_manifest(base_dir, recipe_id, manifest)

    # 1) Rewrite steps (cached in manifest)
    rewritten_steps = manifest.get("rewritten_steps")
    if not isinstance(rewritten_steps, list) or len(rewritten_steps) != len(steps):
        rewritten_steps = rewrite_steps(ingredients=ingredients, steps=steps)
        manifest["rewritten_steps"] = rewritten_steps
        save_manifest(base_dir, recipe_id, manifest)

    # 2) Plan media (cached in manifest)
    plan = manifest.get("plan")
    if not isinstance(plan, dict) or len((plan.get("ingredients") or [])) != len(ingredients) or len((plan.get("steps") or [])) != len(rewritten_steps):
        plan = plan_recipe_media(
            recipe_id=recipe_id,
            ingredients=ingredients,
            original_steps=steps,
            rewritten_steps=rewritten_steps
        )
        manifest["plan"] = plan
        save_manifest(base_dir, recipe_id, manifest)

    img = ImageGen()
    vid = VideoGen()

    failures: List[Dict[str, Any]] = []

    # 3) Generate ingredient images (skip existing)
    for i, item in enumerate(plan.get("ingredients", [])):
        out_abs = os.path.join(ing_dir, f"{i}.png")
        out_rel = f"ingredients/{i}.png"
        if _exists(out_abs):
            mark_item(manifest, "ingredients", i, status="done", files=[out_rel], prompt=item.get("prompt"), text=ingredients[i] if i < len(ingredients) else None)
            save_manifest(base_dir, recipe_id, manifest)
            continue
        try:
            img.generate_png(
                prompt=item["prompt"],
                negative_prompt=item.get("negative_prompt"),
                out_path=out_abs,
            )
            mark_item(manifest, "ingredients", i, status="done", files=[out_rel], prompt=item.get("prompt"), negative_prompt=item.get("negative_prompt"), text=ingredients[i] if i < len(ingredients) else None)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            mark_item(manifest, "ingredients", i, status="failed", error=err, traceback=traceback.format_exc(), text=ingredients[i] if i < len(ingredients) else None)
            failures.append({"section": "ingredients", "index": i, "error": err})
        finally:
            save_manifest(base_dir, recipe_id, manifest)
            gc.collect()

    # 4) Generate step media (skip existing)
    for i, st in enumerate(plan.get("steps", [])):
        media_type = st.get("media_type")
        if media_type not in ("image", "video"):
            media_type = "image"

        step_text = rewritten_steps[i] if i < len(rewritten_steps) else (steps[i] if i < len(steps) else "")

        if media_type == "image":
            out_abs = os.path.join(step_dir, f"{i}.png")
            out_rel = f"steps/{i}.png"

            if _exists(out_abs):
                mark_item(manifest, "steps", i, type="image", status="done", files=[out_rel], prompt=st.get("prompt"), text=step_text)
                save_manifest(base_dir, recipe_id, manifest)
                continue

            try:
                img.generate_png(
                    prompt=st["prompt"],
                    negative_prompt=st.get("negative_prompt"),
                    out_path=out_abs,
                )
                mark_item(manifest, "steps", i, type="image", status="done", files=[out_rel], prompt=st.get("prompt"), negative_prompt=st.get("negative_prompt"), text=step_text)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                mark_item(manifest, "steps", i, type="image", status="failed", error=err, traceback=traceback.format_exc(), text=step_text)
                failures.append({"section": "steps", "index": i, "error": err})
            finally:
                save_manifest(base_dir, recipe_id, manifest)
                gc.collect()

        else:
            cover_abs = os.path.join(step_dir, f"{i}.png")
            cover_rel = f"steps/{i}.png"
            video_abs = os.path.join(step_dir, f"{i}.mp4")
            video_rel = f"steps/{i}.mp4"

            # If video exists, ensure cover exists (extract from video if missing)
            if _exists(video_abs) and _exists(cover_abs):
                mark_item(manifest, "steps", i, type="video", status="done", files=[video_rel, cover_rel], text=step_text)
                save_manifest(base_dir, recipe_id, manifest)
                continue

            if _exists(video_abs) and not _exists(cover_abs):
                try:
                    _extract_cover_from_video(video_abs, cover_abs)
                    mark_item(manifest, "steps", i, type="video", status="done", files=[video_rel, cover_rel], text=step_text)
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
                    mark_item(manifest, "steps", i, type="video", status="failed", error=err, traceback=traceback.format_exc(), text=step_text)
                    failures.append({"section": "steps", "index": i, "error": err})
                finally:
                    save_manifest(base_dir, recipe_id, manifest)
                    gc.collect()
                continue

            tmp = tempfile.mkdtemp(prefix=f"recipe_{recipe_id}_step_{i}_")
            try:
                # Generate the video + cover using the video pipeline
                vid.generate_step_video(
                    shots=st.get("shots") or [],
                    negative_prompt=st.get("negative_prompt"),
                    out_mp4_path=video_abs,
                    out_cover_png_path=cover_abs,
                    target_seconds=int(st.get("target_seconds") or 12),
                    work_dir=tmp,
                )
                mark_item(
                    manifest, "steps", i,
                    type="video",
                    status="done",
                    files=[video_rel, cover_rel],
                    prompt=st.get("prompt"),
                    negative_prompt=st.get("negative_prompt"),
                    target_seconds=int(st.get("target_seconds") or 12),
                    shots=st.get("shots") or [],
                    text=step_text,
                )
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                mark_item(manifest, "steps", i, type="video", status="failed", error=err, traceback=traceback.format_exc(), text=step_text)
                failures.append({"section": "steps", "index": i, "error": err})
            finally:
                keep = os.getenv("KEEP_INTERMEDIATE", "false").lower() == "true"
                if not keep:
                    shutil.rmtree(tmp, ignore_errors=True)
                save_manifest(base_dir, recipe_id, manifest)
                gc.collect()

    # Mark job failed if any failures, but keep partial outputs + manifest (resume friendly)
    if failures:
        raise RuntimeError(
            "Some assets failed. Re-POST the same payload with the same id to resume. "
            f"Failures (first 5): {failures[:5]}"
        )

    return {
        "ok": True,
        "recipe_id": recipe_id,
        "output_dir": out_dir,
        "counts": {"ingredients": len(ingredients), "steps": len(steps)},
        "rewritten_steps_preview": rewritten_steps[: min(5, len(rewritten_steps))],
        "manifest": os.path.join(out_dir, "manifest.json"),
    }
