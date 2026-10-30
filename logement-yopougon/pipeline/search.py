"""Découverte par recherche web (Claude + outil web_search), une fois par jour.

Lit sources/recherches.txt, cherche des vidéos TikTok récentes pour chaque requête et ajoute :
- les vidéos trouvées à data/videos_trouvees.txt (collectées au passage suivant) ;
- les comptes trouvés à data/comptes.json (surveillés à chaque passage).
Inactif sans ANTHROPIC_API_KEY.
"""
import json
import os
import re
import time
from pathlib import Path

import couts

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "sources" / "recherches.txt"
FOUND = ROOT / "data" / "videos_trouvees.txt"
ACCOUNTS = ROOT / "data" / "comptes.json"
CANDIDATES = ROOT / "data" / "comptes_candidats.json"
STATE = ROOT / "data" / "recherche.json"
STATS = ROOT / "data" / "recherche_stats.json"  # par requête : jours lancés, vidéos et comptes trouvés

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
    couts.record(MODEL, response.usage, "recherche")
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
    queries = [l.strip() for l in QUERIES.read_text().splitlines() if l.strip() and not l.startswith("#")]
    done_today = set(state.get("faites", [])) if state.get("derniere") == today else set()
    queries_todo = [q for q in queries if q not in done_today]  # requête ajoutée en cours de journée : lancée seule
    if not queries_todo:
        print("[recherche] déjà faite aujourd'hui")
        return
    import anthropic

    client = anthropic.Anthropic()
    known = set(json.loads(ACCOUNTS.read_text())) if ACCOUNTS.exists() else set()
    cands = json.loads(CANDIDATES.read_text()) if CANDIDATES.exists() else {}
    videos = set(FOUND.read_text().split()) if FOUND.exists() else set()
    new_acc, new_vid = 0, 0
    stats = json.loads(STATS.read_text()) if STATS.exists() else {}
    for q in queries_todo:
        try:
            urls = search(client, q)
        except anthropic.APIError as exc:
            print(f"[recherche] « {q} » : {exc}")
            if isinstance(exc, (anthropic.BadRequestError, anthropic.AuthenticationError)):
                break  # erreur de configuration : inutile de continuer
            continue
        st = stats.setdefault(q, {"lancements": 0, "videos": [], "comptes": []})
        st["lancements"] += 1
        for u in urls:
            if m := TIKTOK_VIDEO.match(u):
                if m.group(2) not in st["videos"]:
                    st["videos"].append(m.group(2))
                url = f"https://www.tiktok.com/@{m.group(1)}/video/{m.group(2)}"
                new_vid += url not in videos
                videos.add(url)
            if m := TIKTOK_ACCOUNT.match(u):
                acc = "@" + m.group(1)
                if acc not in st["comptes"]:
                    st["comptes"].append(acc)
                if acc not in known and acc not in cands:
                    cands[acc] = None  # à examiner au prochain passage
                    new_acc += 1
        print(f"[recherche] « {q} » : {len(urls)} résultats")
    STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    FOUND.write_text("\n".join(sorted(videos)) + "\n")
    CANDIDATES.write_text(json.dumps(cands, ensure_ascii=False, indent=1))
    STATE.write_text(json.dumps({"derniere": today, "faites": sorted(done_today | set(queries_todo)),
                                 "nouveaux_comptes": new_acc, "nouvelles_videos": new_vid}, ensure_ascii=False))
    print(f"[recherche] {new_acc} nouveaux comptes, {new_vid} nouvelles vidéos")


if __name__ == "__main__":
    main()
