"""Lecture d'une annonce par Claude (optionnelle).

Active seulement si le secret ANTHROPIC_API_KEY est défini dans le dépôt
(Settings > Secrets and variables > Actions). Sans clé, ou en cas d'erreur,
renvoie None et les règles d'extract.py prennent le relais.
Modèle : Claude Haiku 5.5 par défaut (le moins cher) ; variable de dépôt CLAUDE_MODEL pour en changer
(ex. claude-opus-5-5, plus précis mais ~40x plus cher).
"""
import base64
import io
import json
import os

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-haiku-5-5"
# repli automatique en cas de refus : pas disponible sur Haiku
FALLBACK = {} if "haiku" in MODEL else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
_disabled = False  # après une erreur de quota/clé, plus d'appel pendant ce passage

PROMPT = """Tu lis une annonce immobilière publiée sur TikTok ou Facebook en Côte d'Ivoire (Abidjan).
Sources : légende, transcription audio automatique (peut contenir des erreurs ou des paroles de musique),
texte lu sur les images (souvent bruité) et quelques images de la vidéo.
Remplis la fiche. Mets null quand l'information est absente : n'invente rien.
Repères : « chambre salon » = 2 pièces ; « 160 000 x5 + 100 000 » = 5 mois à payer + 100 000 F d'agence ;
« bureau comme habitation » = logement utilisable aussi en bureau."""

_INT = {"type": ["integer", "null"]}
_STR = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "est_annonce": {"type": "boolean"},
        "transaction": {"type": ["string", "null"], "enum": ["location", "vente", "cession", None]},
        "commune": _STR,
        "quartier": _STR,
        "type": {
            "type": ["string", "null"],
            "enum": ["studio", "entrée-coucher", "chambre simple", "chambre salon", "2 pièces", "3 pièces",
                     "4 pièces", "5 pièces", "villa", "duplex", "commercial", None],
        },
        "pieces": _INT,
        "loyer": _INT,
        "caution": _INT,
        "avance": _INT,
        "agence": _INT,
        "mois_a_payer": _INT,
        "frais_agence": _INT,
        "frais_visite": _INT,
        "equipements": {"type": "array", "items": {"type": "string"}},
        "resume": {"type": "string"},
    },
    "required": ["est_annonce", "transaction", "commune", "quartier", "type", "pieces", "loyer", "caution",
                 "avance", "agence", "mois_a_payer", "frais_agence", "frais_visite", "equipements", "resume"],
    "additionalProperties": False,
}


def _images(frames, n=3):
    from PIL import Image

    if not frames:
        return []
    picks = [frames[int(i * (len(frames) - 1) / max(n - 1, 1))] for i in range(min(n, len(frames)))]
    out = []
    for f in dict.fromkeys(picks):
        img = Image.open(f).convert("RGB")
        img.thumbnail((768, 768))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=75)
        out.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.standard_b64encode(buf.getvalue()).decode()}})
    return out


def read_listing(description, transcript, ocr, frames):
    global _disabled
    if _disabled or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic

    # clé d'organisation (non rattachée à un espace de travail) : préciser l'espace via ANTHROPIC_WORKSPACE_ID
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": workspace} if workspace else None)
    text = f"LÉGENDE:\n{description}\n\nAUDIO:\n{transcript}\n\nTEXTE DES IMAGES:\n" + "\n".join(ocr)
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=PROMPT,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            **FALLBACK,
            messages=[{"role": "user", "content": _images(frames) + [{"type": "text", "text": text[:8000]}]}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.RateLimitError) as exc:
        print(f"[ia] {type(exc).__name__}, IA suspendue pour ce passage")
        _disabled = True
        return None
    except anthropic.BadRequestError as exc:
        print(f"[ia] requête refusée : {exc}")
        if "workspace" in str(exc):  # problème de configuration : inutile de réessayer pour chaque annonce
            _disabled = True
        return None
    except anthropic.APIError as exc:
        print(f"[ia] erreur : {exc}")
        return None
    if response.stop_reason == "refusal":
        print("[ia] refus du modèle")
        return None
    data = json.loads(next(b.text for b in response.content if b.type == "text"))
    data["_model"] = response.model
    return data


if __name__ == "__main__":  # auto-test : ANTHROPIC_API_KEY=... python pipeline/llm.py
    print(read_listing("Studio à louer Yopougon Niangon Sud, loyer 60 000, 5 mois + 50 000 agence", "", [], []))
