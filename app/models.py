from pydantic import BaseModel, Field
from typing import List, Optional


class RecipeIn(BaseModel):
    id: int
    ingredients: List[str]
    # accept recipe_steps (preferred) and cooking_steps (legacy)
    recipe_steps: List[str] = Field(default_factory=list, alias="cooking_steps")

    class Config:
        populate_by_name = True


class EnqueueResponse(BaseModel):
    job_id: str
    status_url: str


class JobStatus(BaseModel):
    job_id: str
    status: str
    exc_info: Optional[str] = None
    result: Optional[dict] = None


class CategoryEnqueueIn(BaseModel):
    recipe_id: int


class CategoryEnqueueResponse(BaseModel):
    accepted: bool
    message: str
    recipe_id: int
    job_id: str
    status_url: str
