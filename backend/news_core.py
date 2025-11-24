import os
import re
import json
import requests
from bs4 import BeautifulSoup
from slugify import slugify
from datetime import datetime
from dotenv import load_dotenv

from google import genai
from google.genai import types

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("Lütfen .env içine GEMINI_API_KEY ekle.")

client = genai.Client(api_key=API_KEY)

BASE_URL = "https://news.smol.ai"
OUTPUT_DIR = "smol_articles"
SOCIAL_OUTPUT_DIR = "smol_social"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SOCIAL_OUTPUT_DIR, exist_ok=True)

# ---------------------------------------------------------
# 1) news.smol.ai ana sayfadan son haberleri çek
# ---------------------------------------------------------
def fetch_latest_issues(limit=3):
    resp = requests.get(BASE_URL, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    issues = []
    for a in soup.select("a[href^='/issues/']"):
        raw_title = a.get_text(strip=True)
        href = a["href"]
        if href.strip() == "/issues/":
            continue

        url = BASE_URL + href

        m = re.match(r"^([A-Za-z]{3})\s*(\d{1,2})(.*)$", raw_title)
        if m:
            month, day, rest = m.groups()
            date_guess = f"{month} {day}"
            title_part = rest.strip()
        else:
            date_guess = ""
            title_part = raw_title

        title_clean = re.sub(r"Show details$", "", title_part).strip()

        parent = a.find_parent(["li", "div", "article"])
        summary = None
        if parent:
            p = parent.find("p")
            if p:
                summary = p.get_text(strip=True)

        issues.append(
            {
                "raw_title": raw_title,
                "title": title_clean,
                "date": date_guess,
                "url": url,
                "summary": summary,
            }
        )
    return issues[:limit]

# ---------------------------------------------------------
# 2) Gemini ile Medium yazısı üret (HTML)
# ---------------------------------------------------------
def generate_article(item):
    system_instruction = """
Sen Medium uyumlu, semantik HTML yazan bir teknik editörsün.
Yalnızca saf HTML üret:
- Başlıklar: <h1>, <h2>, <h3>
- Paragraflar: <p>
- Listeler: <ul><li>
- Alıntı: <blockquote>
- Kod blokları: <pre><code class="language-python">...</code></pre> (veya uygun dil)
- Görsel gerekiyorsa <figure><img ...><figcaption>...</figcaption></figure>
Kesinlikle Markdown, backtick, meta cümle veya “işte makalen” gibi ifadeler kullanma.
<script> ve inline stil verme.
"""

    user_prompt = f"""
Aşağıdaki AI haberinden, Medium’a yapıştırılınca biçimini koruyan,
zengin HTML bir makale üret.

<requirements>
- 900–1200 kelime.
- En az 1 gerçek, çalışabilir kod bloğu (örnek veriyle).
- Bölümler: <h1>Başlık</h1>, <h2>Neden Önemli?</h2>, <h2>Teknik Öz</h2>,
  <h2>Örnek Kod</h2>, <h2>Kullanım Alanları</h2>, <h2>Riskler/Sınırlılıklar</h2>,
  <h2>Özet</h2>, <h2>Sonraki Adımlar</h2>.
- Türkçe, samimi ama profesyonel.
</requirements>

<news>
Tam başlık: {item['raw_title']}
Ayrıştırılmış başlık: {item['title']}
Tarih (tahmini): {item['date']}
Kaynak: {item['url']}
Kısa özet: {item['summary']}
</news>

<constraints>
Sadece HTML döndür. <script> kullanma. Stil verme.
</constraints>
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",  # gerekirse 'gemini-2.5-flash-lite'
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=12000,
            temperature=0.7,
        ),
    )
    return response.text  # HTML

# (alias – UI tarafı varsa kullanılabilir)
def generate_medium_article(item):
    return generate_article(item)

# ---------------------------------------------------------
# 3) Sosyal medya paketi (JSON)
# ---------------------------------------------------------
def generate_social_package(item):
    system_instruction = """
Sen bir içerik stratejisti ve video/görsel odaklı içerik üreten bir uzmansın.
Her zaman SADECE geçerli JSON döndür.
"""

    user_prompt = f"""
Aşağıdaki AI haberine göre sosyal medya içerik paketi üret:

Haber başlığı: {item['title']}
Tam başlık: {item['raw_title']}
Tarih (tahmini): {item['date']}
Kaynak: {item['url']}
Kısa özet: {item['summary']}

ÇIKTI ŞEMASI (sadece JSON döndür):
{{
  "video_script": "string",
  "carousel_slides": [
    "Slide 1 metni",
    "Slide 2 metni",
    "Slide 3 metni",
    "Slide 4 metni",
    "Slide 5 metni"
  ],
  "personal_comment": "string"
}}
"""

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=4000,
            temperature=0.4,
        ),
    )

    text = response.text.strip()

    # ```json ... ``` korumalısı
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            candidate = parts[1]
            brace_index = candidate.find("{")
            if brace_index != -1:
                text = candidate[brace_index:].strip()

    if not text.startswith("{"):
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            text = text[first:last+1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("[!] JSON parse edilemedi, başlangıç:", text[:400])
        return None

    if not all(k in data for k in ["video_script", "carousel_slides", "personal_comment"]):
        print("[!] Sosyal paket eksik alan içeriyor.")
        return None

    return data

# ---------------------------------------------------------
# 4) Makaleyi HTML olarak diske kaydet
# ---------------------------------------------------------
def save_article(item, html_text: str):
    today = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(item["title"])[:80]
    fname = f"{today}-{slug}.html"
    path = os.path.join(OUTPUT_DIR, fname)

    # Basit metadata’yı HTML yorumuna koy
    header = f"""<!--
title: {item['title']}
date: {today}
source: {item['url']}
original_title: {item['raw_title']}
-->"""

    full_html = header + "\n\n" + html_text

    with open(path, "w", encoding="utf-8") as f:
        f.write(full_html)

    return path

# ---------------------------------------------------------
# 5) Sosyal paket dosyaları
# ---------------------------------------------------------
def save_social_package(item, social_data):
    today = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(item["title"])[:80]
    base_name = f"{today}-{slug}"

    os.makedirs(SOCIAL_OUTPUT_DIR, exist_ok=True)

    # Video Script
