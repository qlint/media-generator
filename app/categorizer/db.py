import os
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor


_db_pool: Optional[SimpleConnectionPool] = None


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    user = os.getenv("DB_USER", "").strip()
    pwd = os.getenv("DB_PASSWORD", "").strip()
    host = os.getenv("DB_HOST", "localhost").strip()
    port = os.getenv("DB_PORT", "5432").strip()
    name = os.getenv("DB_NAME", "").strip()
    if not (user and name):
        raise RuntimeError("DATABASE_URL or DB_USER/DB_NAME must be configured")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"


def get_pool() -> SimpleConnectionPool:
    global _db_pool
    if _db_pool is None:
        _db_pool = SimpleConnectionPool(
            minconn=int(os.getenv("DB_POOL_MIN", "1")),
            maxconn=int(os.getenv("DB_POOL_MAX", "10")),
            dsn=_database_url(),
        )
    return _db_pool


@contextmanager
def get_conn():
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def fetch_pending_recipe_ids(limit: int = 10) -> List[int]:
    q = """
        SELECT r.recipe_id
        FROM app.recipes r
        WHERE COALESCE(r.processed_categories, FALSE) = FALSE
        ORDER BY r.recipe_id
        LIMIT %s
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(q, (limit,))
        return [int(x[0]) for x in cur.fetchall()]


def fetch_recipe_payload(recipe_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT recipe_id, recipe_name, cook_time, calory_count, recipe_description
            FROM app.recipes
            WHERE recipe_id = %s
            """,
            (recipe_id,),
        )
        recipe = cur.fetchone()
        if not recipe:
            return None

        cur.execute(
            """
            SELECT
              CASE
                WHEN ri.quantity IS NOT NULL AND m.abbrev_symbol IS NOT NULL
                  THEN CONCAT(ri.quantity::text, ' ', m.abbrev_symbol, ' ', ri.ingredient)
                WHEN ri.quantity IS NOT NULL
                  THEN CONCAT(ri.quantity::text, ' ', ri.ingredient)
                ELSE ri.ingredient
              END AS ingredient_text
            FROM app.recipe_ingredients ri
            LEFT JOIN app.measurements m ON m.measurement_id = ri.measurement_id
            WHERE ri.recipe_id = %s
            ORDER BY COALESCE(ri.sort_order, 999999), ri.recipe_ingredient_id
            """,
            (recipe_id,),
        )
        ingredients = [row["ingredient_text"] for row in cur.fetchall()]

        cur.execute(
            """
            SELECT step_details
            FROM app.recipe_steps
            WHERE recipe_id = %s
            ORDER BY COALESCE(sort_order, 999999), recipe_step_id
            """,
            (recipe_id,),
        )
        steps = [row["step_details"] for row in cur.fetchall()]

    return {
        "recipe_id": int(recipe["recipe_id"]),
        "recipe_name": recipe.get("recipe_name") or "",
        "cook_time": int(recipe.get("cook_time") or 0),
        "calory_count": str(recipe.get("calory_count") or "").strip(),
        "recipe_description": recipe.get("recipe_description") or "",
        "ingredients": ingredients,
        "steps": steps,
    }


def fetch_broad_categories() -> Dict[str, int]:
    """Return dynamic map: broad_category_name(lowercase) -> broad_category_id"""
    q = "SELECT broad_category_id, broad_category FROM app.broad_categories ORDER BY broad_category_id"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(q)
        rows = cur.fetchall()
    out: Dict[str, int] = {}
    for cid, name in rows:
        if name:
            out[str(name).strip().lower()] = int(cid)
    return out


def save_recipe_categories(recipe_id: int, category_ids: List[int]) -> None:
    """Idempotent save: replace relation rows and set processed_categories=true."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM app.recipes WHERE recipe_id = %s", (recipe_id,))
        if not cur.fetchone():
            conn.rollback()
            raise ValueError(f"Recipe {recipe_id} not found")

        cur.execute("DELETE FROM app.recipe_broad_categories WHERE recipe_id = %s", (recipe_id,))
        if category_ids:
            cur.executemany(
                "INSERT INTO app.recipe_broad_categories (recipe_id, broad_category_id) VALUES (%s, %s)",
                [(recipe_id, int(cid)) for cid in sorted(set(category_ids))]
            )

        cur.execute(
            "UPDATE app.recipes SET processed_categories = TRUE WHERE recipe_id = %s",
            (recipe_id,),
        )
        conn.commit()


def mark_processed_false(recipe_id: int) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE app.recipes SET processed_categories = FALSE WHERE recipe_id = %s",
            (recipe_id,),
        )
        conn.commit()


def check_postgres() -> Dict[str, Any]:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
