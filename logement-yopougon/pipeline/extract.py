"""Structuration : texte brut (légende + audio + image) -> fiche d'annonce.

Règles écrites pour le vocabulaire immobilier ivoirien. Aucun numéro de
téléphone n'est conservé dans la sortie (site/annonces.json).
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site" / "annonces.json"

# ---------------------------------------------------------------- utilitaires

PHONE = re.compile(r"(?:\+?\s?225[\s.\-]*)?\d{2}(?:[\s.\-]*\d{2}){3,5}")
EMAIL = re.compile(r"\S+@\S+")


def strip_phones(text):
    return EMAIL.sub("[contact masqué]", PHONE.sub("[numéro masqué]", text or ""))


def fold(text):
    """minuscules sans accents, espaces normalisés"""
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace(" ", " ").replace("’", "'")
    return re.sub(r"[ \t]+", " ", t)


UNITS = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
    "seize": 16, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
}


def words_to_int(words):
    """'soixante quinze mille' -> 75000 ; renvoie None si non numérique."""
    total, cur, seen = 0, 0, False
    for w in re.split(r"[\s\-]+", words.strip()):
        if not w or w == "et":
            continue
        if w.isdigit():
            cur += int(w)
        elif w in UNITS:
            cur += UNITS[w]
        elif w in ("cent", "cents"):
            cur = (cur or 1) * 100
        elif w in ("mille", "milles", "mil"):
            total += (cur or 1) * 1000
            cur = 0
        elif w in ("million", "millions"):
            total += (cur or 1) * 1_000_000
            cur = 0
        else:
            return None
        seen = True
    return total + cur if seen else None


NUMWORD = r"(?:\d+|" + "|".join(sorted(UNITS, key=len, reverse=True)) + r"|cents?|et)"
WORDNUM = re.compile(r"\b((?:" + NUMWORD + r")(?:[\s\-]+" + NUMWORD + r")*[\s\-]+(?:mille|milles|mil|millions?))\b")


def amounts(text):
    """Toutes les sommes plausibles (5 000 à 5 000 000 FCFA) avec leur position."""
    t = fold(text)
    found = []
    # 75.000 / 75 000 / 75000 / 75,000 (+ éventuel f/fcfa)
    for m in re.finditer(r"(?<![\d])(\d{1,3}(?:[ .,]\d{3})+|\d{4,7})(?![\d])", t):
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) <= 7:
            found.append((int(digits), m.start()))
    # 75k / 75 mille / 75mil / 1,5 million
    for m in re.finditer(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(k|mille|milles|mil|millions?|m)\b", t):
        v = float(m.group(1).replace(",", "."))
        mult = 1_000_000 if m.group(2).startswith("million") or m.group(2) == "m" else 1000
        found.append((int(v * mult), m.start()))
    # soixante-quinze mille
    for m in WORDNUM.finditer(t):
        v = words_to_int(m.group(1))
        if v:
            found.append((v, m.start()))
    return [(v, p) for v, p in found if 5_000 <= v <= 5_000_000 and v % 500 == 0]


def month_count(word):
    word = word.strip()
    return int(word) if word.isdigit() else UNITS.get(word)


# ---------------------------------------------------------------- champs

QUARTIERS = {k: v for k, v in json.loads((ROOT / "sources" / "quartiers.json").read_text()).items() if not k.startswith("_")}


def find_quartier(t):
    best = None
    for name, aliases in QUARTIERS.items():
        for a in aliases:
            m = re.search(r"\b" + re.escape(fold(a)) + r"\b", t)
            # le plus spécifique (alias le plus long) gagne : "niangon sud" > "niangon"
            if m and (best is None or len(a) > best[1]):
                best = (name, len(a))
    return best[0] if best else None


TYPES = [  # (motif, type, nb pièces)
    (r"\b(4|quatre) chambres? (et )?salon", "4 chambres salon", 5),
    (r"\b(3|trois) chambres? (et )?salon", "3 chambres salon", 4),
    (r"\b(2|deux) chambres? (et )?salon", "2 chambres salon", 3),
    (r"\b(une |1 )?chambres? (et |\+ ?)?salon", "chambre salon", 2),
    (r"\bstudio", "studio", 1),
    (r"\bentree[ -]coucher", "entrée-coucher", 1),
    (r"\bduplex", "duplex", None),
    (r"\bvilla", "villa", None),
    (r"\b(magasin|boutique|bureau|local commercial)", "commercial", None),
    (r"\b(\d) ?pieces?", None, None),
    (r"\bchambre simple|\bune chambre\b|\b1 chambre\b", "chambre simple", 1),
]


def find_type(t):
    for pat, typ, pieces in TYPES:
        m = re.search(pat, t)
        if m:
            if typ is None:
                n = int(m.group(1))
                return f"{n} pièces", n
            if typ in ("duplex", "villa"):
                m2 = re.search(r"\b(\d) ?(?:pieces|chambres)", t)
                return typ, (int(m2.group(1)) + (1 if "chambre" in m2.group(0) else 0)) if m2 else None
            return typ, pieces
    return None, None


MOIS = r"(\d{1,2}|un|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|douze)"
CONDITIONS = {
    "caution": r"cautions?|garanties?",
    "avance": r"avances?|loyers? d'avance|mois d'avance",
    "agence": r"agence|commissions?|demarcheurs?|frais de visite",
}


def find_conditions(t):
    out = {}
    for key, kw in CONDITIONS.items():
        m = re.search(MOIS + r"\s*mois\s*(?:de\s*|d')?(?:" + kw + r")", t) or re.search(
            r"(?:" + kw + r")\s*[:=]?\s*(?:de\s*)?" + MOIS + r"\s*mois", t
        )
        if m:
            out[key] = month_count(m.group(1))
    # forme abrégée « 2-2-1 » / « 2/2/1 » : on la garde telle quelle, l'ordre varie selon les annonceurs
    m = re.search(r"\b(\d)\s*[/\-]\s*(\d)\s*[/\-]\s*(\d)\b", t)
    if m and not out:
        out["conditions_brutes"] = "-".join(m.groups())
    return out


def find_loyer(t):
    cands = amounts(t)
    if not cands:
        return None
    keys = [m.start() for m in re.finditer(r"loyer|prix|par mois|/ ?mois|le mois|mensuel|a \d+ ?(?:f|fr|francs|mille)", t)]
    excl = [m.start() for m in re.finditer(r"caution|avance|agence|commission|total|a vendre|vente|terrain", t)]

    def score(c):
        v, p = c
        s = 0
        if keys:
            s -= min(abs(p - k) for k in keys)
        if excl and min(abs(p - k) for k in excl) < 25:
            s -= 200
        if not (15_000 <= v <= 1_500_000):
            s -= 500
        return s

    return max(cands, key=score)[0]


EQUIP = {
    "douche interne": r"douches? (?:et wc )?interne|toilettes? interne|wc interne|sanitaires? interne",
    "cuisine": r"\bcuisine",
    "garage / parking": r"garage|parking",
    "compteur personnel": r"compteurs? (?:personnel|individuel|separe|propre)",
    "carrelé": r"carrel",
    "staffé": r"staff",
    "climatisé": r"climatis|\bclim\b",
    "balcon / terrasse": r"balcon|terrasse",
    "cour unique": r"cour unique|cour privee|seul dans la cour|cour individuelle",
    "cour commune": r"cour commune",
    "gardien": r"gardien",
    "forage / eau": r"forage|chateau d'eau",
    "étage": r"\betage\b|\ben hauteur\b",
    "neuf": r"\bneuf\b|\bnouvelle construction|\bjamais habite",
}


def is_sale(t):
    return bool(re.search(r"a vendre|en vente|\bvends?\b|acd|lot(issement)?|terrain", t)) and not re.search(r"a louer|location", t)


def build(raw, corrections):
    parts = [raw.get("description", ""), raw.get("transcript", ""), " ".join(raw.get("ocr", []))]
    t = fold("\n".join(parts))
    typ, pieces = find_type(t)
    rec = {
        "id": raw["id"],
        "url": raw.get("url"),
        "plateforme": raw.get("platform"),
        "auteur": raw.get("uploader"),
        "date": raw.get("upload_date"),
        "thumb": raw.get("thumb"),
        "quartier": find_quartier(t),
        "yopougon": bool(re.search(r"\byop(ougon|on|)?\b|\byopou", t)) or find_quartier(t) is not None,
        "transaction": "vente" if is_sale(t) else "location",
        "type": typ,
        "pieces": pieces,
        "loyer": find_loyer(t),
        **find_conditions(t),
        "equipements": [k for k, p in EQUIP.items() if re.search(p, t)],
        "resume": strip_phones(raw.get("description", ""))[:400],
        "texte": strip_phones(" ".join(p for p in parts if p))[:2000],
    }
    merge_llm(rec, raw.get("llm"))
    rec.update(corrections.get(raw["id"], {}))
    return rec


def merge_llm(rec, ai):
    """La lecture IA prime sur les règles quand elle a trouvé une valeur."""
    if not ai:
        rec["source_extraction"] = "règles"
        return
    if ai.get("est_annonce") is False:
        rec["masquer"] = True
    for key in ("transaction", "type", "pieces", "loyer", "caution", "avance", "agence"):
        if ai.get(key) not in (None, "", 0):
            rec[key] = ai[key]
    if ai.get("quartier"):
        rec["quartier"] = find_quartier(fold(ai["quartier"])) or ai["quartier"].strip().title()
    commune = fold(ai.get("commune") or "")
    if commune:
        rec["yopougon"] = "yop" in commune
    rec["equipements"] = sorted(set(rec["equipements"]) | set(ai.get("equipements") or []))
    if ai.get("resume"):
        rec["resume"] = strip_phones(ai["resume"])[:400]
    rec["source_extraction"] = "IA"


def main():
    corrections = json.loads((ROOT / "sources" / "corrections.json").read_text())
    annonces = []
    for p in sorted(RAW.glob("*.json")):
        rec = build(json.loads(p.read_text()), corrections)
        if not rec.get("masquer"):
            annonces.append(rec)
    annonces.sort(key=lambda a: a.get("date") or "", reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(annonces, ensure_ascii=False, indent=1))
    print(f"{len(annonces)} annonces -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
