import asyncio
import json
import os
import re
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

app = FastAPI(title="Pronote Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Storage en mémoire (session unique, suffisant pour usage perso) ───
SESSION_CACHE: dict = {}  # {"browser": ..., "context": ..., "page": ..., "logged_in": bool}

# ─── Modèles ───────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

# ─── Helpers ──────────────────────────────────────────────────────────
async def get_or_create_session():
    """Retourne la session Playwright existante ou en crée une nouvelle."""
    global SESSION_CACHE
    if SESSION_CACHE.get("browser") and not SESSION_CACHE["browser"].is_connected():
        SESSION_CACHE = {}

    if not SESSION_CACHE.get("page"):
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        SESSION_CACHE = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page,
            "logged_in": False,
        }

    return SESSION_CACHE["page"]


async def login_toutatice(page, username: str, password: str):
    """Effectue la connexion complète Toutatice → EduConnect → Pronote."""
    try:
        # 1. Aller sur Toutatice
        await page.goto("https://www.toutatice.fr/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1500)

        # 2. Cliquer sur "Je me connecte"
        await page.click("a.btn-login", timeout=10000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)

        # 3. Cliquer sur "Avec ÉduConnect"
        await page.click("button.card-button", timeout=10000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        # 4. Remplir identifiant
        await page.fill("#username", username, timeout=10000)

        # 5. Remplir mot de passe
        await page.fill("#password", password, timeout=10000)

        # 6. Soumettre
        await page.click("#bouton_valider", timeout=10000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(4000)

        # 7. Cliquer sur la vignette Pronote
        pronote_selector = 'a[data-dnma-outil="PRONOTE"]'
        await page.wait_for_selector(pronote_selector, timeout=15000)
        await page.click(pronote_selector)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(5000)

        SESSION_CACHE["logged_in"] = True
        SESSION_CACHE["username"] = username
        SESSION_CACHE["password"] = password
        return True

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de connexion : {str(e)}")


async def ensure_logged_in(page, username: str, password: str):
    """S'assure qu'on est bien connecté, re-login si nécessaire."""
    if not SESSION_CACHE.get("logged_in"):
        await login_toutatice(page, username, password)


def parse_notes_html(html: str) -> list:
    """Parse le HTML des notes Pronote."""
    notes = []
    # Cherche tous les items de notes
    items = re.findall(
        r'aria-label="Note élève\s*:\s*([\d,\.]+)(?:/([\d,\.]+))?">.*?'
        r'<div class="ie-ellipsis">(.*?)</div>.*?'
        r'(?:<div class="ie-ellipsis">(.*?)</div>)?.*?'
        r'<span class="ie-sous-titre">(.*?)</span>.*?'
        r'<time[^>]*datetime="([^"]+)"[^>]*>([^<]+)</time>',
        html,
        re.DOTALL,
    )
    return items


# ─── Routes ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/login")
async def login(req: LoginRequest):
    page = await get_or_create_session()
    await login_toutatice(page, req.username, req.password)
    return {"status": "ok", "message": "Connecté à Pronote avec succès"}


@app.get("/api/notes")
async def get_notes(username: str, password: str, trimestre: int = 2):
    page = await get_or_create_session()
    await ensure_logged_in(page, username, password)

    try:
        # Naviguer vers Notes > Mes notes
        await page.click('[aria-controls*="Liste_niveau2"]', timeout=10000)
        await page.wait_for_timeout(500)
        await page.click('[data-genre="198"]', timeout=10000)
        await page.wait_for_timeout(2000)

        # Sélectionner le trimestre
        if trimestre != 3:  # T3 est souvent par défaut
            await page.click('.ocb-libelle[aria-label*="période"]', timeout=10000)
            await page.wait_for_timeout(500)
            trimestre_map = {1: 0, 2: 1, 3: 2}
            options = await page.query_selector_all('[role="option"]')
            if len(options) > trimestre_map[trimestre]:
                await options[trimestre_map[trimestre]].click()
            await page.wait_for_timeout(2000)

        # Scraper les notes
        await page.wait_for_selector('.liste-focus-grid', timeout=10000)
        notes_html = await page.inner_html('.liste-focus-grid')

        # Parser avec BeautifulSoup
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(notes_html, "html.parser")
        notes = []

        for item in soup.select('[role="treeitem"]'):
            try:
                # Date
                time_el = item.select_one("time")
                date = time_el.get_text(strip=True) if time_el else ""

                # Matière et sous-titre
                titres = item.select(".ie-ellipsis")
                matiere = titres[0].get_text(strip=True) if len(titres) > 0 else ""
                sujet = titres[1].get_text(strip=True) if len(titres) > 1 else ""

                # Moyenne classe/groupe
                sous_titre = item.select_one(".ie-sous-titre")
                moyenne_classe = ""
                if sous_titre:
                    txt = sous_titre.get_text(strip=True)
                    moyenne_classe = re.sub(r'<[^>]+>', '', txt)

                # Note élève
                zone_comp = item.select_one('[aria-label*="Note élève"]')
                note_raw = ""
                note_sur = "20"
                if zone_comp:
                    label = zone_comp.get("aria-label", "")
                    m = re.search(r'Note élève\s*:\s*([\d,\.]+)(?:/([\d,\.]+))?', label)
                    if m:
                        note_raw = m.group(1).replace(",", ".")
                        note_sur = m.group(2).replace(",", ".") if m.group(2) else "20"

                if matiere:
                    notes.append({
                        "date": date,
                        "matiere": matiere,
                        "sujet": sujet,
                        "note": float(note_raw) if note_raw else None,
                        "sur": float(note_sur),
                        "note_sur_20": round(float(note_raw) / float(note_sur) * 20, 2) if note_raw else None,
                        "moyenne_classe": moyenne_classe,
                    })
            except Exception:
                continue

        return {"trimestre": trimestre, "count": len(notes), "notes": notes}

    except Exception as e:
        # Re-login et retry si session expirée
        SESSION_CACHE["logged_in"] = False
        raise HTTPException(status_code=500, detail=f"Erreur scraping notes : {str(e)}")


@app.get("/api/emploi-du-temps")
async def get_edt(username: str, password: str):
    page = await get_or_create_session()
    await ensure_logged_in(page, username, password)

    try:
        await page.wait_for_selector('.liste-cours', timeout=10000)
        edt_html = await page.inner_html('.liste-cours')

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(edt_html, "html.parser")
        cours = []

        for li in soup.select("li.flex-contain"):
            heures = li.select(".container-heures div")
            debut = heures[0].get_text(strip=True) if len(heures) > 0 else ""
            fin = heures[1].get_text(strip=True) if len(heures) > 1 else ""

            infos = li.select(".container-cours li")
            matiere = infos[0].get_text(strip=True) if len(infos) > 0 else ""
            prof = infos[1].get_text(strip=True) if len(infos) > 1 else ""
            salle = infos[2].get_text(strip=True) if len(infos) > 2 else ""
            en_cours = "en-cours" in li.get("class", [])

            couleur_el = li.select_one(".trait-matiere")
            couleur = ""
            if couleur_el:
                style = couleur_el.get("style", "")
                m = re.search(r'background-color\s*:\s*(#[0-9a-fA-F]+)', style)
                couleur = m.group(1) if m else ""

            if matiere:
                cours.append({
                    "debut": debut,
                    "fin": fin,
                    "matiere": matiere,
                    "prof": prof,
                    "salle": salle,
                    "en_cours": en_cours,
                    "couleur": couleur,
                })

        return {"count": len(cours), "cours": cours}

    except Exception as e:
        SESSION_CACHE["logged_in"] = False
        raise HTTPException(status_code=500, detail=f"Erreur scraping EDT : {str(e)}")


@app.get("/api/cantine")
async def get_cantine(username: str, password: str):
    page = await get_or_create_session()
    await ensure_logged_in(page, username, password)

    try:
        # Naviguer vers Communication > Menu
        await page.click('[aria-controls*="Liste_niveau6"]', timeout=10000)
        await page.wait_for_timeout(500)
        await page.click('[data-genre="10"]', timeout=10000)
        await page.wait_for_timeout(2000)

        await page.wait_for_selector('.menu-cantine', timeout=10000)
        cantine_html = await page.inner_html('.menu-cantine')

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(cantine_html, "html.parser")
        menus = []

        for jour_div in soup.select('.ctn-liste'):
            date_el = jour_div.select_one('.ctn-date h2')
            if not date_el:
                continue
            date_text = date_el.get_text(strip=True)

            plats = []
            for aliment in jour_div.select('.aliment'):
                texte = aliment.get_text(strip=True)
                is_bio = bool(aliment.select_one('.icon_cantine_bio'))
                plats.append({"plat": texte, "bio": is_bio})

            menus.append({"jour": date_text, "plats": plats})

        return {"count": len(menus), "menus": menus}

    except Exception as e:
        SESSION_CACHE["logged_in"] = False
        raise HTTPException(status_code=500, detail=f"Erreur scraping cantine : {str(e)}")


@app.get("/api/status")
async def status():
    return {
        "status": "running",
        "logged_in": SESSION_CACHE.get("logged_in", False),
        "user": SESSION_CACHE.get("username", None),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/logout")
async def logout():
    global SESSION_CACHE
    try:
        if SESSION_CACHE.get("browser"):
            await SESSION_CACHE["browser"].close()
        if SESSION_CACHE.get("pw"):
            await SESSION_CACHE["pw"].stop()
    except Exception:
        pass
    SESSION_CACHE = {}
    return {"status": "ok", "message": "Déconnecté"}
