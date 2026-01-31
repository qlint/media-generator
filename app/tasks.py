import os
import shutil
import tempfile
import gc
from typing import Dict, Any

from app.media.step_rewriter import rewrite_steps
from app.media.planner import plan_recipe_media
from app.media.image_gen import ImageGen
from app.media.video_gen import VideoGen

def generate_assets_job(recipe: Dict[str, Any]) -> Dict[str, Any]:
    recipe_id = int(recipe["id"])
    ingredients = recipe.get("ingredients", [])
    steps = recipe.get("recipe_steps", [])

    base_dir = os.getenv("ASSETS_BASE_DIR", "/data/assets")
    out_dir = os.path.join(base_dir, str(recipe_id))
    ing_dir = os.path.join(out_dir, "ingredients")
    step_dir = os.path.join(out_dir, "steps")
    os.makedirs(ing_dir, exist_ok=True)
    os.makedirs(step_dir, exist_ok=True)

    # 1) Rewrite steps to be more suitable for storyboarding / T2V prompts
    rewritten_steps = rewrite_steps(ingredients=ingredients, steps=steps)

    # 2) Plan media types + prompts + shots (uses rewritten steps)
    plan = plan_recipe_media(
        recipe_id=recipe_id,
        ingredients=ingredients,
        original_steps=steps,
        rewritten_steps=rewritten_steps
    )

    img = ImageGen()
    vid = VideoGen()

    # 3) Generate ingredient images
    for i, item in enumerate(plan["ingredients"]):
        path = os.path.join(ing_dir, f"{i}.png")
        img.generate_png(
            prompt=item["prompt"],
            negative_prompt=item["negative_prompt"],
            out_path=path,
        )

    # 4) Generate step media
    for i, st in enumerate(plan["steps"]):
        media_type = st["media_type"]
        if media_type == "image":
            path = os.path.join(step_dir, f"{i}.png")
            img.generate_png(
                prompt=st["prompt"],
                negative_prompt=st["negative_prompt"],
                out_path=path,
            )
        else:
            # Generate video + cover image
            cover_path = os.path.join(step_dir, f"{i}.png")
            video_path = os.path.join(step_dir, f"{i}.mp4")

            tmp = tempfile.mkdtemp(prefix=f"recipe_{recipe_id}_step_{i}_")
            try:
                vid.generate_step_video(
                    shots=st["shots"],
                    negative_prompt=st["negative_prompt"],
                    out_mp4_path=video_path,
                    out_cover_png_path=cover_path,
                    target_seconds=int(st.get("target_seconds") or 12),
                    work_dir=tmp,
                )
            finally:
                keep = os.getenv("KEEP_INTERMEDIATE", "false").lower() == "true"
                if not keep:
                    shutil.rmtree(tmp, ignore_errors=True)

        gc.collect()

    return {
        "recipe_id": recipe_id,
        "output_dir": out_dir,
        "counts": {"ingredients": len(ingredients), "steps": len(steps)},
        "rewritten_steps_preview": rewritten_steps[: min(5, len(rewritten_steps))]
    }
