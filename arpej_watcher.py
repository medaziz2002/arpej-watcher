#!/usr/bin/env python3
"""
arpej_watcher.py - Version serveur cloud (compatible Render Free Tier)
"""

import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from bs4 import BeautifulSoup

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "aziz-arpej-alertes-9f31")

RESIDENCES_URLS = [
    "https://www.arpej.fr/fr/residence/jacques-henri-lartigue-residence-etudiante-courbevoie/",
    "https://www.arpej.fr/fr/residence/residence-etudiants-joinville-le-pont-les-nouveaux-ponts-arpej-2/",
    "https://www.arpej.fr/fr/residence/residence-etudiante-saint-mande/",
    "https://www.arpej.fr/fr/residence/saint-mande-residence-etudiante-paris/",
    "https://www.arpej.fr/fr/residence/eugene-chevreul-residence-etudiante-massy/",
    "https://www.arpej.fr/fr/residence/val-pompadour-residence-etudiante-valenton/",
    "https://www.arpej.fr/fr/residence/volti-residence-etudiante-cachan/",
    "https://www.arpej.fr/fr/residence/nicolas-appert-residence-etudiante-ivry-sur-seine/",
    "https://www.arpej.fr/fr/residence/du-parc-residence-etudiante-charenton-le-pont/",
    "https://www.arpej.fr/fr/residence/porte-ditalie-residence-etudiante-le-kremlin-bicetre/",
]

STATE_FILE = Path(__file__).parent / "arpej_state.json"
REQUEST_TIMEOUT = 12
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def send_notification(title: str, message: str, url: str) -> None:
    clean_title = clean_text(title)
    try:
        resp = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": clean_title.encode("utf-8"),
                "Priority": "high",
                "Tags": "house,bell",
                "Click": url,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        print(f"[OK] Notification envoyée : {clean_title}")
    except requests.RequestException as e:
        print(f"[ERREUR] Échec de notification : {e}", file=sys.stderr)


def parse_residence(session: requests.Session, url: str) -> dict | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERREUR] Impossible de charger {url} : {e}", file=sys.stderr)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    title_tag = soup.find("h1")
    name = clean_text(title_tag.get_text()) if title_tag else url.strip("/").split("/")[-1].replace("-", " ").title()

    availability = 0
    m = re.search(r"(\d+)\s+logements?\s+disponibles?", text, re.IGNORECASE)
    if m:
        availability = int(m.group(1))

    price_match = re.search(r"partir de\s*([\d\s.,]+)\s*€", text, re.IGNORECASE)
    price = price_match.group(1).strip() if price_match else "?"

    return {"name": name, "availability": availability, "price": price, "url": url}


def check_once() -> None:
    state = load_state()
    session = requests.Session()

    for url in RESIDENCES_URLS:
        info = parse_residence(session, url)
        if info is None:
            continue

        previous = state.get(url, {}).get("availability", 0)
        current = info["availability"]

        print(f"[{current} dispo(s)] {info['name']}")

        if current > previous:
            send_notification(
                title=f"Logement disponible : {info['name']}",
                message=(
                    f"{current} logement(s) disponible(s) dès {info['price']} €/mois.\n"
                    f"Résidence : {info['name']}\n"
                    f"Lien : {info['url']}"
                ),
                url=info["url"],
            )

        state[url] = {"availability": current, "name": info["name"]}
        time.sleep(0.3)

    save_state(state)


def scraper_worker() -> None:
    print("[DÉMARRAGE] Boucle de scraping lancée (toutes les 60s)...")
    while True:
        try:
            check_once()
        except Exception as e:
            print(f"[ERREUR BOUCLE] {e}", file=sys.stderr)
        time.sleep(60)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Watcher ARPEJ actif")

    def log_message(self, format: str, *args: object) -> None:
        return  # Évite d'encombrer les logs avec les health checks


def run_http_server() -> None:
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"[HTTP] Serveur d'écoute prêt sur le port {port}")
    server.serve_forever()


if __name__ == "__main__":
    t = threading.Thread(target=scraper_worker, daemon=True)
    t.start()
    run_http_server()