from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from news_core import (
    fetch_latest_issues,
    generate_article,
    generate_social_package,
    save_article,
    save_social_package,
)

app = FastAPI(title="AI News Backend")

# CORS (frontend localhost'tan çağırırken sorun olmasın diye)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # istersen sadece http://localhost:5173 vs yazarsın
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------- Pydantic modelleri ---------
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


# --------- API endpoint'leri ---------


@app.get("/api/issues", response_model=List[Issue])
def get_issues(limit: int = 3):
    """
    news.smol.ai'den son haberleri çek.
    Frontend buradan listeyi alacak.
    """
    issues = fetch_latest_issues(limit=limit)
    return issues


@app.post("/api/generate/medium", response_model=MediumResponse)
def generate_medium_article(req: GenerateRequest, save: bool = False):
    """
    Verilen haberden Medium formatında markdown makale üret.
    İsteğe bağlı olarak md dosyasını da kaydedebilir.
    """
    issue_dict = req.issue.dict()
    markdown = generate_article(issue_dict)

    saved_path = None
    if save:
        saved_path = save_article(issue_dict, markdown)

    return MediumResponse(markdown=markdown, saved_path=saved_path)


@app.post("/api/generate/social", response_model=SocialResponse)
def generate_social(req: GenerateRequest, save: bool = False):
    """
    Verilen haberden sosyal medya paketi üret
    (video script + carousel + yorum).
    """
    issue_dict = req.issue.dict()
    social = generate_social_package(issue_dict)
    if social is None:
        # Çok basit bir hata cevabı, frontend'te kontrol edersin
        raise RuntimeError("Sosyal paket üretilemedi (JSON sorunu olabilir).")

    saved_paths = None
    if save:
        saved_paths = save_social_package(issue_dict, social)

    return SocialResponse(
        social=SocialPackage(**social),
        saved_paths=saved_paths,
    )
