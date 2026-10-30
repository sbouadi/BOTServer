"""Alertes Telegram : un message par nouvelle annonce affichée sur le site.

Configuration (une fois) :
1. Sur Telegram, écrire à @BotFather, commande /newbot, récupérer le jeton.
2. Secret GitHub TELEGRAM_BOT_TOKEN = ce jeton.
3. Écrire /start à son bot : le chat est détecté tout seul au passage suivant.
Inactif sans jeton. Au premier lancement, les annonces déjà présentes ne sont pas renvoyées (un seul résumé).
"""
import html
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ANNONCES = ROOT / "site" / "annonces.json"
SENT = ROOT / "data" / "alertes_envoyees.json"
CHATS = ROOT / "data" / "telegram.json"
SITE = "https://sbouadi.github.io/BOTServer/"
MAX_PER_RUN = 15  # au-delà, un seul message récapitulatif


def fmt(n):
    return f"{n:,}".replace(",", " ") + " F" if n else None


def api(token, method, **params):
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=30)
    data = r.json()
    if not data.get("ok"):
        print(f"[alerte] {method} : {data.get('description')}")
    return data


def chat_ids(token):
    """Chats déjà connus + ceux qui ont écrit au bot depuis (ex. /start)."""
    known = json.loads(CHATS.read_text()) if CHATS.exists() else []
    for upd in api(token, "getUpdates").get("result", []):
        chat = (upd.get("message") or {}).get("chat") or {}
        if chat.get("id") and chat["id"] not in known:
            known.append(chat["id"])
            api(token, "sendMessage", chat_id=chat["id"],
                text="✅ Alertes Logement Yopougon activées. Vous recevrez chaque nouvelle annonce correspondant aux filtres.")
    CHATS.write_text(json.dumps(known))
    return known


def message(a):
    cond = [f"{a['mois_a_payer']} mois à l'entrée" if a.get("mois_a_payer") else None,
            f"+ {fmt(a['frais_agence'])} agence" if a.get("frais_agence") else None,
            f"visite {fmt(a['frais_visite'])}" if a.get("frais_visite") else None]
    lieu = a.get("quartier") or "Yopougon"
    if a.get("precision_lieu"):
        lieu += f" ({a['precision_lieu']})"
    lines = [
        f"🏠 <b>{html.escape(a.get('type') or 'Logement')}</b> · {html.escape(lieu)}",
        f"💰 <b>{fmt(a['loyer']) or 'prix non indiqué'}</b> / mois",
    ]
    if any(cond):
        lines.append("📋 " + " · ".join(c for c in cond if c))
    if a.get("total_entree"):
        lines.append(f"🔑 Pour entrer : <b>{fmt(a['total_entree'])}</b>")
    if a.get("equipements"):
        lines.append("✔️ " + html.escape(", ".join(a["equipements"][:6])))
    for n in a.get("contacts") or []:
        pretty = " ".join(n[i:i + 2] for i in range(0, 10, 2))
        lines.append(f"📞 {pretty} · <a href=\"https://wa.me/225{n}\">WhatsApp</a>")
    lines.append(f"▶️ <a href=\"{html.escape(a['url'])}\">Voir l'annonce</a>")
    return "\n".join(lines)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not ANNONCES.exists():
        return
    annonces = json.loads(ANNONCES.read_text())
    first_run = not SENT.exists()
    sent = set(json.loads(SENT.read_text())) if SENT.exists() else set()
    chats = chat_ids(token)
    if not chats:
        print("[alerte] aucun chat : écrire /start au bot Telegram")
        return  # on n'enregistre rien : les annonces partiront dès qu'un chat sera connu
    new = [a for a in annonces if a["id"] not in sent]
    if first_run:
        for c in chats:
            api(token, "sendMessage", chat_id=c, parse_mode="HTML", disable_web_page_preview=True,
                text=f"📊 {len(annonces)} annonces correspondent déjà à vos filtres : <a href=\"{SITE}\">voir le site</a>.\n"
                     "Vous recevrez désormais chaque nouvelle annonce ici.")
        new = []
    for a in new[:MAX_PER_RUN]:
        for c in chats:
            api(token, "sendMessage", chat_id=c, text=message(a), parse_mode="HTML", disable_web_page_preview=False)
    if len(new) > MAX_PER_RUN:
        for c in chats:
            api(token, "sendMessage", chat_id=c, parse_mode="HTML",
                text=f"… et {len(new) - MAX_PER_RUN} autres nouvelles annonces : <a href=\"{SITE}\">voir le site</a>.")
    SENT.write_text(json.dumps(sorted(sent | {a["id"] for a in annonces})))
    print(f"[alerte] {len(new)} nouvelle(s) annonce(s) envoyée(s) à {len(chats)} chat(s)")


if __name__ == "__main__":
    main()
