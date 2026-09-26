"""HTTP surface for the editable prompt store (see app/prompt_store.py).

Mounted from app/main.py the same way app/dashboard.py's router is --
behind the app-wide bearer-token dependency, no router-level auth of its
own. This is the C4 contract other agents (the frontend Prompts panel,
`rona edit prompt`) build against verbatim; do not change these shapes
without updating them too.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import i18n
from app import prompt_store

router = APIRouter(prefix="/api")


class PromptUpdate(BaseModel):
    content: str
    base_version: str


@router.get("/prompts")
async def list_prompts():
    return {
        "prompts": prompt_store.list_prompts(),
        "placeholders": prompt_store.placeholder_values(),
        "max_bytes": prompt_store.MAX_PROMPT_BYTES,
    }


@router.get("/prompts/{prompt_id}")
async def get_prompt(prompt_id: str):
    try:
        return prompt_store.read(prompt_id)
    except prompt_store.PromptNotFound:
        raise HTTPException(404, i18n.t("prompts.not_found")) from None


@router.put("/prompts/{prompt_id}")
async def put_prompt(prompt_id: str, payload: PromptUpdate):
    try:
        return prompt_store.write(prompt_id, payload.content, payload.base_version)
    except prompt_store.PromptNotFound:
        raise HTTPException(404, i18n.t("prompts.not_found")) from None
    except prompt_store.PromptConflict:
        raise HTTPException(409, i18n.t("prompts.conflict")) from None
    except prompt_store.PromptValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str):
    try:
        return prompt_store.reset(prompt_id)
    except prompt_store.PromptNotFound:
        raise HTTPException(404, i18n.t("prompts.not_found")) from None
