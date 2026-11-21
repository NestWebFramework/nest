"""The theme's regions in the admin panel (Themes → Regions): the blocks the site's
modules offer, placed in the places the theme in use has room for (a sidebar, the footer,
the home page), each with its settings, in their order. No template is touched: the theme
shows a region with {{ region("name") }} (nest.regions), and the choice is kept in the
workspace. Administrators only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from nest_auth import CurrentUser, require_role

from nest import regions as nest_regions
from nest import render, toast, translator

router = APIRouter()
admin_only = require_role("admin")


def _page(request: Request, *, problems: list[str] | None = None, status_code: int = 200) -> Any:
    nest = request.app.state.nest
    placed = nest_regions.load(nest.workspace)
    blocks = nest_regions.offered(nest)
    return render(
        request,
        "admin/regions.html",
        status_code=status_code,
        regions=nest_regions.theme_regions(nest),
        placed=placed,
        blocks=blocks,
        problems=problems or [],
    )


@router.get("/themes/regions")
def regions_page(request: Request, user: CurrentUser = Depends(admin_only)):
    return _page(request)


def _back(request: Request, to: str = "") -> RedirectResponse:
    target = (
        to
        if to.startswith("/") and not to.startswith("//")
        else f"{request.app.state.nest.admin_root}/themes/regions"
    )
    return RedirectResponse(target, status_code=303)


@router.post("/themes/regions/add")
async def add_block(request: Request, user: CurrentUser = Depends(admin_only)):
    """A block in a region: "module.block", its region, its settings (setting:<name>)."""
    nest = request.app.state.nest
    t = translator(request)
    form = await request.form()
    region = str(form.get("region", ""))
    module, _, block = str(form.get("block", "")).partition(".")
    offer = nest_regions.offered(nest).get((module, block))
    names = {r.name for _theme, r in nest_regions.theme_regions(nest)}
    if offer is None or region not in names:
        return _page(
            request, problems=[t("Choose a block and a region of this theme.")], status_code=400
        )
    settings = {k: str(form.get(f"setting:{k}", "")).strip()[:200] for k in offer.settings}
    placed = nest_regions.load(nest.workspace)
    placed.setdefault(region, []).append(
        nest_regions.Placement(module, block, {k: v for k, v in settings.items() if v})
    )
    nest_regions.save(nest.workspace, placed)
    toast(request, t("The block is placed."))
    return _back(request, str(form.get("back", "")))


@router.post("/themes/regions/{region}/{index:int}")
async def change_block(
    request: Request, region: str, index: int, user: CurrentUser = Depends(admin_only)
):
    """up, down, remove, or save its settings."""
    nest = request.app.state.nest
    form = await request.form()
    action = str(form.get("action", ""))
    placed = nest_regions.load(nest.workspace)
    items = placed.get(region, [])
    if not 0 <= index < len(items):
        raise HTTPException(404)
    if action == "up" and index > 0:
        items[index - 1], items[index] = items[index], items[index - 1]
    elif action == "down" and index < len(items) - 1:
        items[index + 1], items[index] = items[index], items[index + 1]
    elif action == "remove":
        items.pop(index)
    elif action == "save":
        offer = nest_regions.offered(nest).get((items[index].module, items[index].block))
        keys = offer.settings if offer is not None else items[index].settings
        items[index].settings = {
            k: v for k in keys if (v := str(form.get(f"setting:{k}", "")).strip()[:200])
        }
    nest_regions.save(nest.workspace, placed)
    return _back(request, str(form.get("back", "")))
