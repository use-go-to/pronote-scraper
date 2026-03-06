# 🎓 Pronote Scraper — Dashboard Web

Dashboard web pour scraper tes notes, emploi du temps et menu cantine Pronote via Toutatice/EduConnect, sans Selenium, déployable **gratuitement** sur Render.

---

## 🏗️ Stack

- **Backend** : FastAPI + Playwright (Chromium headless)
- **Scraping** : BeautifulSoup4
- **Frontend** : HTML/CSS/JS (intégré, pas de framework)
- **Hébergement** : Render (free tier)

---

## 🚀 Déploiement — Guide pas à pas

### 1. Créer le repo GitHub

```bash
# Dans ce dossier :
git init
git add .
git commit -m "Initial commit — Pronote scraper"
```

Va sur [github.com/new](https://github.com/new) → crée un repo `pronote-scraper` (privé recommandé !) → puis :

```bash
git remote add origin https://github.com/TON_USERNAME/pronote-scraper.git
git branch -M main
git push -u origin main
```

### 2. Créer le service sur Render

1. Va sur [render.com](https://render.com) → **New > Web Service**
2. Connecte ton GitHub et sélectionne `pronote-scraper`
3. Configure :
   - **Name** : `pronote-scraper`
   - **Runtime** : `Python 3`
   - **Build Command** : `./build.sh`
   - **Start Command** : `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan** : `Free`
4. Clique **Create Web Service**

> ⏳ Le premier build prend ~3-5 min (installation de Chromium)

### 3. Utiliser le dashboard

Accède à `https://ton-service.onrender.com` → entre tes identifiants EduConnect → profite !

---

## 📡 API Endpoints

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/` | Dashboard web |
| `POST` | `/api/login` | Connexion Toutatice |
| `GET` | `/api/notes?username=&password=&trimestre=2` | Notes par trimestre |
| `GET` | `/api/emploi-du-temps?username=&password=` | EDT du jour |
| `GET` | `/api/cantine?username=&password=` | Menu cantine semaine |
| `GET` | `/api/status` | Statut de la session |
| `POST` | `/api/logout` | Déconnexion |

---

## ⚠️ Notes importantes

- **Free tier Render** : L'instance "dort" après 15 min d'inactivité → premier appel ~30s (cold start). Ensuite fluide.
- **Session** : La session Playwright est maintenue en mémoire. Si le serveur redémarre, il faut se reconnecter.
- **Sécurité** : Déploie le repo en **privé** sur GitHub. Ne partage pas l'URL publique si tu y mets des credentials en dur.
- **Usage perso** : Ce projet est pour usage personnel uniquement, conformément aux CGU de Pronote/Toutatice.

---

## 🔧 Dev local

```bash
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
uvicorn main:app --reload
# Ouvre http://localhost:8000
```
