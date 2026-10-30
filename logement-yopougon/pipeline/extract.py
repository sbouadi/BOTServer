"""Structuration : texte brut (légende + audio + image) -> fiche d'annonce.

Règles écrites pour le vocabulaire immobilier ivoirien. Aucun numéro de
téléphone n'est conservé dans la sortie (site/annonces.json).
"""
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site" / "annonces.json"

# ---------------------------------------------------------------- utilitaires

PHONE = re.compile(r"(?:\+?\s?225[\s.\-]*)?\d{2}(?:[\s.\-]*\d{2}){3,5}")
EMAIL = re.compile(r"\S+@\S+")


CI_PHONE = re.compile(r"(?<!\d)(?:\+?\s?225[\s.\-]*)?((?:0[157]|2[157])(?:[\s.\-]*\d{2}){4})(?!\d)")


def find_phones(*texts):
    """Numéros ivoiriens à 10 chiffres, normalisés (0707123456), sans doublon."""
    out = []
    for text in texts:
        for m in CI_PHONE.finditer(text or ""):
            n = re.sub(r"\D", "", m.group(1))
            if len(n) == 10 and n not in out:
                out.append(n)
    return out[:3]


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
    for m in re.finditer(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(k|mille|milles|mlle|mle|mil|millions?|m)\b", t):
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
    (r"\bentree[ -]couche[re]?", "entrée-coucher", 1),
    (r"\bduplex", "duplex", None),
    (r"\bvilla", "villa", None),
    (r"\b0?(\d) ?pieces?", None, None),
    (r"\b(magasin|boutique|local commercial)|\bbureau(?! comme habitation)", "commercial", None),
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
    # « 6 mois + 100 000 », « 160 000 x5 plus 100 000 », « 150k - 6 + 100k », « 5MOIS+100MIL »
    montant = r"(\d[\d .,]*\s*(?:k|mille|mlle|mle|mil|f|fr|fcfa)?)"
    m = (re.search(r"(\d{1,2})\s*mois\s*(?:\+|plus)\s*" + montant, t)
         or re.search(r"(?<![a-z])x\s*(\d{1,2})\s*(?:\+|plus)\s*" + montant, t)
         or re.search(r"[-–]\s*(\d{1,2})\s*(?:\+|plus)\s*" + montant, t))
    if m:
        out["mois_a_payer"] = int(m.group(1))
        frais = amounts(m.group(2))
        if frais:
            out["frais_agence"] = frais[0][0]
    elif m2 := re.search(r"[-–]\s*(\d{1,2})\s*mois\b", t):  # « 170k - 5mois »
        out["mois_a_payer"] = int(m2.group(1))
    m = re.search(r"visite[^0-9]{0,20}" + montant, t)
    if m and amounts(m.group(1)):
        out["frais_visite"] = amounts(m.group(1))[0][0]
    # forme abrégée « 2-2-1 » / « 2/2/1 » : on la garde telle quelle, l'ordre varie selon les annonceurs
    m = re.search(r"\b(\d)\s*[/\-]\s*(\d)\s*[/\-]\s*(\d)\b", t)
    if m and not any(k in out for k in ("caution", "avance", "mois_a_payer")):
        out["conditions_brutes"] = "-".join(m.groups())
    return out


def find_loyer(t):
    cands = amounts(t)
    if not cands:
        return None
    keys = [m.start() for m in re.finditer(r"loyer|prix|par mois|/ ?mois|le mois|mensuel|a \d+ ?(?:f|fr|francs|mille)", t)]
    excl = [m.start() for m in re.finditer(r"caution|avance|agence|commission|visite|total|a vendre|vente|terrain|\+", t)]

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
    "usage bureau possible": r"bureau comme habitation|habitation (ou|comme) bureau",
    "neuf": r"\bneuf\b|\bnouvelle (construction|maison)|\bjamais habite",
    "plusieurs salles d'eau": r"\b[2-4] salles? d'?eaux?",
}


def is_sale(t):
    return bool(re.search(r"a vendre|en vente|\bvends?\b|acd|lot(issement)?|terrain|cession|a ceder", t)) and not re.search(r"a louer|location", t)


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
        "transaction": ("cession" if re.search(r"cession|a ceder", t) else "vente") if is_sale(t) else "location",
        "type": typ,
        "pieces": pieces,
        "loyer": find_loyer(t),
        **find_conditions(t),
        "equipements": [k for k, p in EQUIP.items() if re.search(p, t)],
        "resume": (raw.get("description") or "")[:400],
        "texte": " ".join(p for p in parts if p)[:2000],
        "contacts": find_phones(raw.get("description"), " ".join(raw.get("ocr", [])), raw.get("transcript")),
    }
    merge_llm(rec, raw.get("llm"))
    if raw.get("origine") == "découverte" and (not rec["yopougon"] or rec["transaction"] == "vente"):
        rec["masquer"] = True  # vidéo trouvée automatiquement mais hors sujet
    rec.update(corrections.get(raw["id"], {}))
    rec["type"] = TYPE_CANON.get(rec.get("type"), rec.get("type"))
    rec["total_entree"] = entry_cost(rec)
    return rec


def entry_cost(rec):
    """Somme à sortir pour entrer dans le logement, quand l'annonce permet de la calculer."""
    loyer = rec.get("loyer")
    if not loyer:
        return None
    mois = rec.get("mois_a_payer") or (
        (rec.get("caution") or 0) + (rec.get("avance") or 0) + (rec.get("agence") or 0) or None
    )
    if not mois:
        return None
    return loyer * mois + (rec.get("frais_agence") or 0)


TYPE_CANON = {  # une seule étiquette par taille de logement, pour que le filtre ne les sépare pas
    "chambre salon": "2 pièces", "2 chambres salon": "3 pièces",
    "3 chambres salon": "4 pièces", "4 chambres salon": "5 pièces",
}


def merge_llm(rec, ai):
    """Combine règles et IA : chacune là où elle est la plus fiable (mesuré sur 61 vidéos).

    - type et quartier : règles d'abord (motifs explicites, liste de quartiers de référence), IA en secours ;
    - montants et conditions : IA d'abord (lit le contexte, ex. « 230 000 » vs « 1 230 000 »), règles en secours.
    """
    if not ai:
        rec["source_extraction"] = "règles"
        return
    if ai.get("est_annonce") is False:
        rec["masquer"] = True
    if ai.get("transaction"):
        rec["transaction"] = ai["transaction"]
    for key in ("type", "pieces"):
        if rec.get(key) is None and ai.get(key) not in (None, "", 0):
            rec[key] = ai[key]
    for key in ("loyer", "caution", "avance", "agence", "mois_a_payer", "frais_agence", "frais_visite"):
        if ai.get(key) not in (None, "", 0):
            rec[key] = ai[key]
    if ai.get("quartier"):
        precis = ai["quartier"].strip()
        if not rec.get("quartier"):
            rec["quartier"] = find_quartier(fold(precis)) or precis.title()
        if fold(precis) != fold(rec["quartier"]):
            rec["precision_lieu"] = precis
    commune = fold(ai.get("commune") or "")
    if commune:
        rec["yopougon"] = "yop" in commune
    rec["equipements"] = sorted(set(rec["equipements"]) | set(ai.get("equipements") or []))
    if ai.get("resume"):
        rec["resume"] = strip_phones(ai["resume"])[:400]
    rec["source_extraction"] = "règles + IA"


def dedupe(annonces):
    """Les agents republient souvent la même annonce : on garde la plus récente."""
    seen, out = {}, []
    for a in annonces:  # déjà triées de la plus récente à la plus ancienne
        key = (a.get("auteur"), a.get("type"), a.get("quartier"), a.get("loyer"))
        if None in key[1:] or key not in seen:
            if None not in key[1:]:
                seen[key] = a
                a["publications"] = 1
            out.append(a)
        else:
            seen[key]["publications"] += 1
            seen[key].setdefault("autres_liens", []).append(a["url"])
    return out


def main():
    corrections = json.loads((ROOT / "sources" / "corrections.json").read_text())
    annonces = []
    files = sorted(RAW.glob("*.json"))
    for i, p in enumerate(files, 1):
        raw = json.loads(p.read_text())
        if i % 10 == 0 or i == len(files):
            print(f"[progression] {i}/{len(files)} ({100 * i // len(files)} %)")
        if raw.get("llm") is None and raw.get("llm_essais", 0) < 3 and os.environ.get("ANTHROPIC_API_KEY"):
            # rattrapage : relecture IA (texte seul) des annonces collectées sans IA
            import llm

            if not llm._disabled:
                raw["llm"] = llm.read_listing(raw.get("description", ""), raw.get("transcript", ""), raw.get("ocr", []), [])
                if not llm._disabled:
                    raw["llm_essais"] = raw.get("llm_essais", 0) + 1
                p.write_text(json.dumps(raw, ensure_ascii=False, indent=1))
        rec = build(raw, corrections)
        if not rec.get("masquer"):
            annonces.append(rec)
    annonces.sort(key=lambda a: a.get("date") or "", reverse=True)
    annonces = dedupe(annonces)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(annonces, ensure_ascii=False, indent=1))
    print(f"{len(annonces)} annonces -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
