import asyncio
import json
import os
import re
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# Logs détaillés visibles dans Render dashboard
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Pronote Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_CACHE: dict = {}

class LoginRequest(BaseModel):
    username: str
    password: str

async def get_or_create_session():
    global SESSION_CACHE
    if SESSION_CACHE.get("browser") and not SESSION_CACHE["browser"].is_connected():
        log.warning("Browser déconnecté, reset session")
        SESSION_CACHE = {}

    if not SESSION_CACHE.get("page"):
        log.info("Lancement de Playwright + Chromium...")
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--no-zygote",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-background-networking",
                "--mute-audio",
            ]
        )
        log.info("Chromium lancé ✅")
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
        log.info("Session Playwright créée ✅")

    return SESSION_CACHE["page"]


async def login_toutatice(page, username: str, password: str):
    try:
        import socket
        try:
            socket.create_connection(("www.toutatice.fr", 443), timeout=5)
            log.info("Réseau OK - toutatice.fr accessible ✅")
        except Exception as ne:
            log.error(f"Réseau KO - toutatice.fr inaccessible ❌ : {ne}")
        log.info("Étape 1 : Navigation vers toutatice.fr...")
        await page.goto("https://www.toutatice.fr/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        log.info(f"Page chargée : {page.url}")

        log.info("Étape 2 : Clic sur 'Je me connecte'...")
        await page.click("a.btn-login", timeout=10000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        log.info(f"Après clic login : {page.url}")

        log.info("Étape 3 : Clic sur 'Avec ÉduConnect'...")
        await page.click("button.card-button", timeout=10000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)
        log.info(f"Après EduConnect : {page.url}")

        log.info("Étape 4 : Saisie identifiant...")
        await page.fill("#username", username, timeout=10000)

        log.info("Étape 5 : Saisie mot de passe...")
        await page.fill("#password", password, timeout=10000)

        log.info("Étape 6 : Soumission du formulaire...")
        await page.click("#bouton_valider", timeout=10000)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(5000)
        log.info(f"Après login EduConnect : {page.url}")

        log.info("Étape 7 : Recherche vignette Pronote...")
        pronote_selector = 'a[data-dnma-outil="PRONOTE"]'
        await page.wait_for_selector(pronote_selector, timeout=20000)
        log.info("Vignette Pronote trouvée ✅")
        await page.click(pronote_selector)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(5000)
        log.info(f"Pronote chargé : {page.url}")

        SESSION_CACHE["logged_in"] = True
        SESSION_CACHE["username"] = username
        SESSION_CACHE["password"] = password
        log.info("Connexion complète ✅")
        return True

    except Exception as e:
        # Capture screenshot pour debug
        try:
            await page.screenshot(path="/tmp/debug_screenshot.png")
            log.error(f"Screenshot sauvegardé dans /tmp/debug_screenshot.png")
            current_url = page.url
            log.error(f"URL au moment de l'erreur : {current_url}")
            html_snippet = await page.content()
            log.error(f"HTML (500 chars) : {html_snippet[:500]}")
        except Exception as se:
            log.error(f"Impossible de capturer debug : {se}")
        raise HTTPException(status_code=500, detail=f"Erreur étape login : {str(e)}")


async def ensure_logged_in(page, username: str, password: str):
    if not SESSION_CACHE.get("logged_in"):
        await login_toutatice(page, username, password)


def parse_notes_html(html: str) -> list:
    notes = []
    return notes


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/login")
async def login(req: LoginRequest):
    log.info(f"Tentative de login pour : {req.username}")
    page = await get_or_create_session()
    await login_toutatice(page, req.username, req.password)
    return {"status": "ok", "message": "Connecté à Pronote avec succès"}


@app.get("/api/notes")
async def get_notes(username: str, password: str, trimestre: int = 2):
    page = await get_or_create_session()
    await ensure_logged_in(page, username, password)

    try:
        log.info("Navigation vers Notes > Mes notes...")
        await page.click('[aria-controls*="Liste_niveau2"]', timeout=10000)
        await page.wait_for_timeout(500)
        await page.click('[data-genre="198"]', timeout=10000)
        await page.wait_for_timeout(2000)

        if trimestre != 3:
            await page.click('.ocb-libelle[aria-label*="période"]', timeout=10000)
            await page.wait_for_timeout(500)
            trimestre_map = {1: 0, 2: 1, 3: 2}
            options = await page.query_selector_all('[role="option"]')
            if len(options) > trimestre_map[trimestre]:
                await options[trimestre_map[trimestre]].click()
            await page.wait_for_timeout(2000)

        await page.wait_for_selector('.liste-focus-grid', timeout=10000)
        notes_html = await page.inner_html('.liste-focus-grid')

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(notes_html, "html.parser")
        notes = []

        for item in soup.select('[role="treeitem"]'):
            try:
                time_el = item.select_one("time")
                date = time_el.get_text(strip=True) if time_el else ""
                titres = item.select(".ie-ellipsis")
                matiere = titres[0].get_text(strip=True) if len(titres) > 0 else ""
                sujet = titres[1].get_text(strip=True) if len(titres) > 1 else ""
                sous_titre = item.select_one(".ie-sous-titre")
                moyenne_classe = sous_titre.get_text(strip=True) if sous_titre else ""
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
                    "debut": debut, "fin": fin, "matiere": matiere,
                    "prof": prof, "salle": salle, "en_cours": en_cours, "couleur": couleur,
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
        log.info("Navigation vers Communication > Menu...")
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
