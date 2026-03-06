#!/usr/bin/env bash
# build.sh — exécuté par Render au déploiement
set -e

echo "📦 Installation des dépendances Python..."
pip install -r requirements.txt

echo "🌐 Installation de Chromium pour Playwright..."
playwright install chromium

echo "🔧 Installation des dépendances système pour Chromium..."
playwright install-deps chromium

echo "✅ Build terminé !"
