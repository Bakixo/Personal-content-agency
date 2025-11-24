import os
from typing import List, Optional, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .news_core import (
    fetch_latest_issues,
    generate_article,          # <-- makale üretimi
    generate_social_package,   # <-- sosyal paket üretimi
    save_article,              # <-- md kaydetme
    save_social_package,       # <-- sosyal paket dosyalarını kaydetme
)

app = FastAPI(title="Personal Content Agency")

# (Opsiyonel) Frontend farklı origin’deyse aç:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # istersen domain ile daralt
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Static / Frontend ----------
# /static altında css/js/asset’leri servisle
app.mount("/static", StaticFiles(directory="frontend", html=True), name="static")

# Root isteğinde index.html ver
@app.get("/", include_in_schema=False)
async def serve_frontend():
    index_path = os.path.join("frontend", "index.html")
    return FileResponse(index_path)

# Basit sağlık kontrolü
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}

# ---------- Pydantic Modeller ----------
class Issue(BaseModel):
    raw_title: str
    title: str
    date: str
    url: str
    summary: Optional[str] = None

class SocialPackage(BaseModel):
    video_script: str
    carousel_slides: List[str]
    personal_comment: str

class GenerateRequest(BaseModel):
    issue: Issue

class MediumResponse(BaseModel):
    markdown: str
    saved_path: Optional[str] = None

class SocialResponse(BaseModel):
    social: SocialPackage
    saved_paths: Optional[Dict[str, str]] = None

# ---------- API ----------
@app.get("/api/issues", response_model=List[Issue])
def api_get_issues(limit: int = 3):
    return fetch_latest_issues(limit=limit)

@app.post("/api/generate/medium", response_model=MediumResponse)
def api_generate_medium(req: GenerateRequest, save: bool = False):
    issue_dict = req.issue.dict()
    markdown = generate_article(issue_dict)

    saved_path = save_article(issue_dict, markdown) if save else None
    return MediumResponse(markdown=markdown, saved_path=saved_path)

@app.post("/api/generate/social", response_model=SocialResponse)
def api_generate_social(req: GenerateRequest, save: bool = False):
    issue_dict = req.issue.dict()
    social = generate_social_package(issue_dict)
    if social is None:
        # Frontend’e düzgün hata dönmek istersen HTTPException fırlatabilirsin
        raise RuntimeError("Sosyal paket üretilemedi (JSON sorunu olabilir).")

    saved_paths = save_social_package(issue_dict, social) if save else None
    return SocialResponse(social=SocialPackage(**social), saved_paths=saved_paths)
