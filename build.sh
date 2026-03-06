#!/usr/bin/env bash
# build.sh — exécuté par Render au déploiement
set -e

echo "📦 Installation des dépendances Python..."
pip install -r requirements.txt

echo "🌐 Installation de Chromium dans le dossier projet..."
# Dossier dans /src qui persiste au runtime
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/.browsers
playwright install chromium

echo "✅ Build terminé !"
