#!/usr/bin/env python3
"""
arpej_watcher.py
Surveille la disponibilité des résidences ARPEJ (92 et 94)
et envoie une notification push via ntfy.sh dès qu'un logement se libère.

Conçu pour tourner sur GitHub Actions (voir .github/workflows/arpej.yml) :
le topic ntfy est lu depuis la variable d'environnement NTFY_TOPIC
(un secret GitHub côté serveur), avec une valeur par défaut pour les
tests en local.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "aziz-arpej-alertes-9f31")

RESIDENCES_URLS = [
    # Hauts-de-Seine — 92
    "https://www.arpej.fr/fr/residence/jacques-henri-lartigue-residence-etudiante-courbevoie/",

    # Val-de-Marne — 94
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
    if title_tag:
        name = clean_text(title_tag.get_text())
    else:
        name = url.strip("/").split("/")[-1].replace("-", " ").title()

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


def main() -> None:
    # Si lancé avec --once, une seule passe (pour les tests rapides)
    if "--once" in sys.argv:
        check_once()
        return

    # Boucle de 4 minutes (4 passages espacés de 60s) pour couvrir l'intervalle
    # entre deux déclenchements GitHub Actions (planifiés toutes les 5 min)
    for i in range(4):
        print(f"--- Vérification {i+1}/4 ---")
        check_once()
        if i < 3:
            time.sleep(60)


if __name__ == "__main__":
    main()