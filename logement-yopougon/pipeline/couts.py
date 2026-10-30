"""Suivi des coûts API Claude, par jour, dans data/couts.json.

Tarifs officiels (platform.claude.com/docs/en/about-claude/pricing, vérifiés le 30/10/2026), en $ par million de jetons.
"""
import json
import time
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "data" / "couts.json"
PRICES = {  # (entrée, sortie) pour des requêtes de moins de 100 000 jetons
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
WEB_SEARCH = 10 / 1000  # 10 $ pour 1 000 recherches


def record(model, usage, poste):
    """Ajoute l'usage d'une réponse API au total du jour (poste : 'lecture' ou 'recherche')."""
    p_in, p_out = PRICES.get(model, PRICES["claude-opus-5-5"])  # modèle inconnu : tarif le plus haut, par prudence
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    cost = usage.input_tokens / 1e6 * p_in + usage.output_tokens / 1e6 * p_out + searches * WEB_SEARCH
    data = json.loads(FILE.read_text()) if FILE.exists() else {}
    day = data.setdefault(time.strftime("%Y-%m-%d"), {})
    d = day.setdefault(poste, {"appels": 0, "jetons_entree": 0, "jetons_sortie": 0, "recherches_web": 0, "cout_usd": 0.0})
    d["appels"] += 1
    d["jetons_entree"] += usage.input_tokens
    d["jetons_sortie"] += usage.output_tokens
    d["recherches_web"] += searches
    d["cout_usd"] = round(d["cout_usd"] + cost, 4)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1))
