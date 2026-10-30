"""Découverte par recherche web (Claude + outil web_search), une fois par jour.

Lit sources/recherches.txt, cherche des vidéos TikTok récentes pour chaque requête et ajoute :
- les vidéos trouvées à data/videos_trouvees.txt (collectées au passage suivant) ;
- les comptes trouvés à data/comptes.json (surveillés à chaque passage).
Inactif sans ANTHROPIC_API_KEY.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "sources" / "recherches.txt"
FOUND = ROOT / "data" / "videos_trouvees.txt"
ACCOUNTS = ROOT / "data" / "comptes.json"
STATE = ROOT / "data" / "recherche.json"

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-haiku-5-5"
TIKTOK_VIDEO = re.compile(r"https?://(?:www\.)?tiktok\.com/@([\w.\-]+)/video/(\d+)")
TIKTOK_ACCOUNT = re.compile(r"https?://(?:www\.)?tiktok\.com/@([\w.\-]+)")


def search(client, query):
    """Renvoie les URL des résultats de recherche (sans dépendre du texte rédigé par le modèle)."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        messages=[{
            "role": "user",
            "content": f"Cherche des vidéos TikTok récentes d'annonces de location : « {query} » "
                       f"(Abidjan, Côte d'Ivoire). Utilise la recherche web, par exemple « {query} tiktok ».",
        }],
    )
    urls = []
    for block in response.content:
        if block.type == "web_search_tool_result" and isinstance(block.content, list):
            urls += [r.url for r in block.content if getattr(r, "url", None)]
        elif block.type == "text":
            urls += re.findall(r"https?://\S+", block.text)
    return urls


def main():
    if not os.environ.get("ANTHROPIC_API_KEY") or not QUERIES.exists():
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    today = time.strftime("%Y-%m-%d")
    signature = hashlib.sha1(QUERIES.read_bytes()).hexdigest()[:12]
    if state.get("derniere") == today and state.get("requetes") == signature:
        print("[recherche] déjà faite aujourd'hui")
        return  # une liste de requêtes modifiée relance la recherche le jour même
    import anthropic

    client = anthropic.Anthropic()
    queries = [l.strip() for l in QUERIES.read_text().splitlines() if l.strip() and not l.startswith("#")]
    accounts = set(json.loads(ACCOUNTS.read_text())) if ACCOUNTS.exists() else set()
    videos = set(FOUND.read_text().split()) if FOUND.exists() else set()
    new_acc, new_vid = 0, 0
    for q in queries:
        try:
            urls = search(client, q)
        except anthropic.APIError as exc:
            print(f"[recherche] « {q} » : {exc}")
            if isinstance(exc, (anthropic.BadRequestError, anthropic.AuthenticationError)):
                break  # erreur de configuration : inutile de continuer
            continue
        for u in urls:
            if m := TIKTOK_VIDEO.match(u):
                url = f"https://www.tiktok.com/@{m.group(1)}/video/{m.group(2)}"
                new_vid += url not in videos
                videos.add(url)
            if m := TIKTOK_ACCOUNT.match(u):
                acc = "@" + m.group(1)
                new_acc += acc not in accounts
                accounts.add(acc)
        print(f"[recherche] « {q} » : {len(urls)} résultats")
    FOUND.write_text("\n".join(sorted(videos)) + "\n")
    ACCOUNTS.write_text(json.dumps(sorted(accounts), ensure_ascii=False, indent=1))
    STATE.write_text(json.dumps({"derniere": today, "requetes": signature, "nouveaux_comptes": new_acc, "nouvelles_videos": new_vid}))
    print(f"[recherche] {new_acc} nouveaux comptes, {new_vid} nouvelles vidéos")


if __name__ == "__main__":
    main()
