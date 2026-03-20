from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from maestro.templates import render

router = APIRouter(prefix="/legal")


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return render(request, "legal-privacy.html", {})


@router.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return render(request, "legal-terms.html", {})
