"""Lecture d'une annonce par modèle de langage (GitHub Models, jeton Actions intégré).

Optionnel : sans jeton ou en cas d'erreur, renvoie None et les règles d'extract.py prennent le relais.
"""
import base64
import json
import os
import re

import requests

ENDPOINT = "https://models.github.ai/inference/chat/completions"
MODELS = ["openai/gpt-4.1-mini", "openai/gpt-4o-mini"]
_quota_hit = False  # après un refus de quota, plus d'appel IA pendant ce passage

PROMPT = """Tu lis une annonce immobilière publiée sur TikTok ou Facebook en Côte d'Ivoire (Abidjan).
Sources : légende, transcription audio automatique (peut contenir des erreurs), texte lu sur les images, et quelques images.
Réponds UNIQUEMENT par un objet JSON avec ces clés (null si l'information est absente, n'invente rien) :
{
 "est_annonce": bool,            // vraie offre de logement ?
 "transaction": "location"|"vente"|null,
 "commune": str|null,            // ex. "Yopougon", "Cocody"
 "quartier": str|null,           // sous-quartier tel qu'écrit, ex. "Niangon Sud"
 "type": "studio"|"entrée-coucher"|"chambre simple"|"chambre salon"|"2 chambres salon"|"3 chambres salon"|"4 chambres salon"|"villa"|"duplex"|"commercial"|null,
 "pieces": int|null,             // chambre salon = 2, 2 chambres salon = 3...
 "loyer": int|null,              // FCFA par mois
 "caution": int|null,            // en mois
 "avance": int|null,             // en mois
 "agence": int|null,             // commission / démarcheur, en mois
 "mois_a_payer": int|null,       // nombre total de mois de loyer à verser à l'entrée (ex. "160 000 x5" -> 5, "6 mois + 100k" -> 6)
 "frais_agence": int|null,       // montant FCFA en plus des mois (ex. "+100 000" -> 100000)
 "frais_visite": int|null,       // FCFA
 "equipements": [str],           // ex. "douche interne", "compteur personnel", "cour unique", "garage / parking", "carrelé", "staffé", "climatisé", "balcon / terrasse", "cuisine", "neuf", "étage"
 "resume": str                   // 1 phrase factuelle, sans numéro de téléphone
}"""


def _frames_payload(frames, n=3):
    if not frames:
        return []
    picks = [frames[int(i * (len(frames) - 1) / max(n - 1, 1))] for i in range(min(n, len(frames)))]
    out = []
    for f in dict.fromkeys(picks):
        from PIL import Image
        import io

        img = Image.open(f).convert("RGB")
        img.thumbnail((512, 512))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        out.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}})
    return out


def read_listing(description, transcript, ocr, frames):
    global _quota_hit
    token = os.environ.get("GITHUB_TOKEN")
    if not token or _quota_hit:
        return None
    text = f"LÉGENDE:\n{description}\n\nAUDIO:\n{transcript}\n\nTEXTE DES IMAGES:\n" + "\n".join(ocr)
    content = [{"type": "text", "text": text[:6000]}] + _frames_payload(frames)
    for model in MODELS:
        for attempt in range(1):
            try:
                r = requests.post(
                    ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    allow_redirects=False,
                    json={
                        "model": model,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": content}],
                    },
                    timeout=90,
                )
                if r.status_code == 429:  # quota gratuit épuisé : on réessaiera au prochain passage
                    print(f"[llm] quota atteint ({r.headers.get('retry-after', '?')} s), IA suspendue pour ce passage")
                    _quota_hit = True
                    return None
                if r.status_code != 200 or not r.text.strip().startswith("{"):
                    print(f"[llm] {model} HTTP {r.status_code} {r.headers.get('content-type')} {r.headers.get('location', '')}: {r.text[:300]!r}")
                    break
                raw = r.json()["choices"][0]["message"]["content"]
                data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
                data["_model"] = model
                return data
            except Exception as exc:
                print(f"[llm] {model} essai {attempt + 1}: {exc}")
                break
    return None


if __name__ == "__main__":  # auto-test : python pipeline/llm.py
    print(read_listing("Studio à louer Yopougon Niangon Sud, loyer 60 000, 5 mois + 50 000 agence", "", [], []))
