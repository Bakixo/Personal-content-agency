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

    # /issues/... linklerini yakala
    for a in soup.select("a[href^='/issues/']"):
        raw_title = a.get_text(strip=True)
        href = a["href"]

        # sadece /issues/ ise (liste sayfası) atla
        if href.strip() == "/issues/":
            continue

        url = BASE_URL + href

        # Örnek raw_title:
        # "Nov 19OpenAI fires back: GPT 5.1 Codex (API) and GPT 5.1 Pro (ChatGPT)Show details"
        # "Nov 18Gemini 3 Pro — new GDM frontier model 6, Gemini 3 Deep Think, and Antigravity IDEShow details"

        # 1) Başta "Mon dd" şeklinde tarih varsa ayıkla (Nov 19, Dec 3 vs.)
        m = re.match(r"^([A-Za-z]{3})\s*(\d{1,2})(.*)$", raw_title)
        if m:
            month, day, rest = m.groups()
            date_guess = f"{month} {day}"
            title_part = rest.strip()
        else:
            date_guess = ""
            title_part = raw_title

        # 2) Sondaki "Show details" kısmını at
        title_clean = re.sub(r"Show details$", "", title_part).strip()

        # Özet (varsa): parent içinde ilk <p>
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
# 2) Gemini ile Medium yazısı üret
# ---------------------------------------------------------
def generate_article(item):
    system_instruction = """
Sen bir üniversite istatistik ve veri bilimi topluluğu için Medium makaleleri yazan
profesyonel bir teknik editörsün.

Görevlerin:
- Sana verilen haberlerden, doğrudan yayımlanmaya hazır makale metni üret.
- Asla "işte hazırladığım makale", "harika bir görev" gibi meta cümleler yazma.
- Kendinden bahsetme, sadece yazının içeriğini yaz.
- Okuyucuya "topluluğumuzun sayfasına hoş geldiniz" gibi cümlelerle hitap edebilirsin.

Tarz:
- Açıklayıcı, sade, samimi
- Gerektiğinde madde işaretleri ve başlıklar (##, ###)
- En az 800 kelime
- Sonunda mutlaka "## Özet" ve "## Sonraki Adımlar" bölümleri olsun.
"""

    user_prompt = f"""
Aşağıdaki AI haberini al ve Türkçe, detaylı bir Medium makalesine dönüştür:

Tam başlık: {item['raw_title']}
Ayrıştırılmış başlık: {item['title']}
Tarih (tahmini): {item['date']}
Kaynak: {item['url']}
Kısa özet: {item['summary']}

Makale:
- Haber neden önemli? Aç
- Teknik kısmı öğrencilerin anlayacağı şekilde sadeleştir
- Firmanın, modelin, olayın bağlamını ver
- Öğrenciler için ne ifade ettiği üzerine dur
- Kod örneği gerekiyorsa basit bir örnek ekle
- Sonunda "Özet" ve "Sonraki Adımlar" başlıkları mutlaka olsun

Çıktıyı tamamen Markdown formatında ver.
"""

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=12000,  # biraz yükselttik ki metin kesilmesin
            temperature=0.7,
        ),
    )

    return response.text

def generate_medium_article(item):
    """
    Streamlit / UI tarafında kullanılmak üzere,
    generate_article fonksiyonunun alias'ı.
    """
    return generate_article(item)

# ---------------------------------------------------------
# 3) Sosyal medya paketi üret
#    (video script + carousel + kişisel yorum) JSON olarak
# ---------------------------------------------------------
def generate_social_package(item):
    system_instruction = """
Sen bir içerik stratejisti ve video/görsel odaklı içerik üreten bir uzmansın.
Görevlerin:
- Haberleri, kısa video script'i, carousel metni ve kişisel yorum haline getirip
  sosyal medya için hazır hale getirmek.
- Çıktıyı her zaman geçerli, parse edilebilir JSON formatında döndürmek.
- Asla JSON dışına çıkmamak, açıklama yazmamak, backtick kullanmamak.
"""

    user_prompt = f"""
Aşağıdaki AI haberine göre sosyal medya içerik paketi üret:

Haber başlığı: {item['title']}
Tam başlık: {item['raw_title']}
Tarih (tahmini): {item['date']}
Kaynak: {item['url']}
Kısa özet: {item['summary']}

İçerik türleri:

1) video_script:
- TikTok / Reels için 45–60 saniyelik bir script.
- 8–12 kısa cümle olsun.
- İlk cümle dikkat çekici bir "hook" olsun.
- Teknik terimleri çok basit açıkla.
- Sonda "Benim yorumum:" diye başlayan 2–3 cümlelik kişisel değerlendirme ekle.

2) carousel_slides:
- 5 elemanlı bir dizi (array) olsun.
- Slide 1: Başlık + alt başlık (kısa).
- Slide 2: Haber özeti → 3 madde halinde.
- Slide 3: Teknik yenilikler → 3 madde halinde.
- Slide 4: "Bu ne işe yarar?" → 3 madde halinde.
- Slide 5: "Benim yorumum" → 3 madde halinde.
- Her slide için tek bir string üret; içinde satır sonu ile maddeleri yazabilirsin.

3) personal_comment:
- Bu haberle ilgili 4–6 cümlelik kişisel teknik yorum.
- Ton: samimi, öğrencilerle konuşur gibi, ama bilgi dolu.
- Gelecek hakkında ufak bir tahmin ve öğrencilere minik bir tavsiye içersin.

ÇIKTI FORMATIN:

Aşağıdaki JSON iskeletini DOLDUR ve SADECE JSON döndür:

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
            temperature=0.4,  # biraz disipline çekelim
        ),
    )

    text = response.text.strip()

    # 1) Eğer ```json ... ``` gibi code fence varsa, içini alalım
    if text.startswith("```"):
        # ör: ```json\n{...}\n```
        parts = text.split("```")
        # parts[1] = "json\n{...}" olabilir
        if len(parts) >= 3:
            candidate = parts[1]
            # "json\n{...}" içinden { ile başlayan kısmı bul
            brace_index = candidate.find("{")
            if brace_index != -1:
                text = candidate[brace_index:].strip()

    # 2) Hâlâ başta/sonda çöplük varsa, ilk { ile son } arasını al
    if not text.startswith("{"):
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            text = text[first:last+1]

    # 3) Şimdi JSON'a parse etmeyi dene
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("[!] Sosyal paket JSON parse edilemedi, ham çıktı şu şekilde başladı:")
        print(text[:400])  # debug için ilk 400 karakteri göster
        return None

    # 4) Minimum alanlar var mı?
    if not all(k in data for k in ["video_script", "carousel_slides", "personal_comment"]):
        print("[!] Sosyal paket eksik alan içeriyor.")
        return None

    return data


# ---------------------------------------------------------
# 4) Medium makaleyi Markdown olarak kaydet
# ---------------------------------------------------------
def save_article(item, markdown_text):
    today = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(item["title"])[:80]
    fname = f"{today}-{slug}.md"
    path = os.path.join(OUTPUT_DIR, fname)

    frontmatter = f"""---
title: "{item['title']}"
date: {today}
source: "{item['url']}"
original_title: "{item['raw_title']}"
---

"""

    full_markdown = frontmatter + "\n" + markdown_text

    with open(path, "w", encoding="utf-8") as f:
        f.write(full_markdown)

    return path


# ---------------------------------------------------------
# 5) Sosyal paket çıktılarını dosyalara kaydet
# ---------------------------------------------------------
def save_social_package(item, social_data):
    today = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(item["title"])[:80]

    base_name = f"{today}-{slug}"
    output_dir = "smol_social"
    os.makedirs(output_dir, exist_ok=True)

    # 1) Video Script (çok satırlı hale getir)
    video_text = social_data["video_script"].replace("\\n", "\n")
    path_video = os.path.join(output_dir, f"{base_name}-video_script.txt")

    with open(path_video, "w", encoding="utf-8") as f:
        f.write(video_text)

    # 2) Carousel slides (5 slayt)
    path_carousel = os.path.join(output_dir, f"{base_name}-carousel_slides.txt")
    with open(path_carousel, "w", encoding="utf-8") as f:
        for i, slide in enumerate(social_data["carousel_slides"], start=1):
            f.write(f"--- Slide {i} ---\n")
            f.write(slide.replace("\\n", "\n"))
            f.write("\n\n")

    # 3) Personal comment
    comment_text = social_data["personal_comment"].replace("\\n", "\n")
    path_comment = os.path.join(output_dir, f"{base_name}-personal_comment.txt")

    with open(path_comment, "w", encoding="utf-8") as f:
        f.write(comment_text)

    return {
        "video_script": path_video,
        "carousel_slides": path_carousel,
        "personal_comment": path_comment
    }



# ---------------------------------------------------------
# 6) Ana akış
# ---------------------------------------------------------
def main():
    print("news.smol.ai'den haberler çekiliyor...")

    issues = fetch_latest_issues(limit=2)  # istersen 3 yap
    if not issues:
        print("Hiç issue bulunamadı. HTML yapısı değişmiş olabilir.")
        return

    for item in issues:
        print(f"\n[+] Haber bulundu: {item['raw_title']}")
        print(f"URL: {item['url']}")

        # 1) Medium makalesi
        article = generate_article(item)
        article_path = save_article(item, article)
        print(f"    → Medium taslağı (md) oluşturuldu: {article_path}")

        # 2) Sosyal medya paketi
        social = generate_social_package(item)
        if social:
            paths = save_social_package(item, social)
            print("    → Sosyal paket oluşturuldu:")
            print(f"       - Video script: {paths['video_script']}")
            print(f"       - Carousel:     {paths['carousel_slides']}")
            print(f"       - Yorum:        {paths['personal_comment']}")
        else:
            print("    [!] Sosyal paket üretilemedi (JSON sorunu olabilir).")


