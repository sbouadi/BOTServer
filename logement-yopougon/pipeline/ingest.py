"""Collecte : télécharge les annonces, transcrit l'audio, lit le texte des images.

Sortie : un fichier data/raw/<id>.json par annonce (texte brut, avant structuration).
Les annonces déjà traitées sont ignorées : le script peut tourner en boucle.
"""
import json
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import yt_dlp

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
THUMBS = ROOT / "site" / "thumbs"
WORK = ROOT / "work"
ERRORS = ROOT / "data" / "errors.json"

MAX_DISCOVERY_PER_PAGE = 40
MAX_NEW_PER_RUN = 60


def read_list(name):
    path = ROOT / "sources" / name
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]


def discover(pages):
    """Liste les vidéos des pages hashtag / compte, sans les télécharger."""
    urls = []
    opts = {"quiet": True, "extract_flat": True, "playlistend": MAX_DISCOVERY_PER_PAGE, "ignoreerrors": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        for page in pages:
            try:
                info = ydl.extract_info(page, download=False) or {}
                for e in info.get("entries") or []:
                    if e and (e.get("url") or e.get("webpage_url")):
                        urls.append(e.get("webpage_url") or e["url"])
                print(f"[découverte] {page}: {len(info.get('entries') or [])} vidéos")
            except Exception as exc:  # une page cassée ne doit pas tout arrêter
                print(f"[découverte] {page}: échec {exc}")
    return urls


def download(url):
    WORK.mkdir(exist_ok=True)
    opts = {
        "quiet": True,
        "outtmpl": str(WORK / "%(id)s.%(ext)s"),
        "format": "best[height<=720]/best",
        "writethumbnail": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    files = sorted(WORK.glob(f"{info['id']}.*"))
    media = next((f for f in files if f.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov", ".m4a", ".mp3")), None)
    thumb = next((f for f in files if f.suffix.lower() in (".jpg", ".jpeg", ".webp", ".png", ".image")), None)
    return info, media, thumb


_whisper = None


def transcribe(media):
    global _whisper
    from faster_whisper import WhisperModel

    if _whisper is None:
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    # décodage par ffmpeg (évite les incompatibilités PyAV de faster-whisper)
    import numpy as np

    pcm = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(media), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    if audio.size == 0:
        return ""
    segments, _ = _whisper.transcribe(audio, language="fr", vad_filter=True, beam_size=5)
    return " ".join(s.text.strip() for s in segments).strip()


def ocr_frames(media, vid):
    """Une image toutes les 2 s, OCR français, lignes dédoublonnées."""
    import pytesseract
    from PIL import Image

    fdir = WORK / f"{vid}_frames"
    fdir.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(media), "-vf", "fps=1/2,scale=720:-1", str(fdir / "f%03d.png")],
        check=False,
    )
    seen, lines = set(), []
    frames = sorted(fdir.glob("*.png"))
    for f in frames:
        text = pytesseract.image_to_string(Image.open(f), lang="fra")
        for line in text.splitlines():
            line = re.sub(r"\s+", " ", line).strip()
            key = line.lower()
            # on écarte le bruit OCR : lignes trop courtes ou sans lettres/chiffres utiles
            if len(line) >= 4 and re.search(r"[A-Za-z0-9]{3}", line) and key not in seen:
                seen.add(key)
                lines.append(line)
    return lines, frames


def save_thumb(vid, thumb, frames):
    from PIL import Image

    THUMBS.mkdir(parents=True, exist_ok=True)
    src = thumb or (frames[0] if frames else None)
    if not src:
        return None
    try:
        img = Image.open(src).convert("RGB")
        img.thumbnail((360, 640))
        out = THUMBS / f"{vid}.jpg"
        img.save(out, "JPEG", quality=70)
        return f"thumbs/{vid}.jpg"
    except Exception:
        return None


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    done_ids = {p.stem for p in RAW.glob("*.json")}
    done_urls = set()
    for p in RAW.glob("*.json"):
        d = json.loads(p.read_text())
        done_urls.update(filter(None, [d.get("source_url"), d.get("url")]))

    errors = json.loads(ERRORS.read_text()) if ERRORS.exists() else {}
    candidates = read_list("urls.txt") + discover(read_list("discovery.txt"))
    queue = [u for u in dict.fromkeys(candidates) if u not in done_urls and errors.get(u, {}).get("tries", 0) < 3]
    print(f"{len(queue)} annonces à traiter")

    new = 0
    for url in queue[:MAX_NEW_PER_RUN]:
        try:
            info, media, thumb = download(url)
            vid = f"tt_{info['id']}" if "tiktok" in (info.get("extractor") or "").lower() else f"{info.get('extractor','x').lower()}_{info['id']}"
            if vid in done_ids:
                continue
            transcript = transcribe(media) if media else ""
            ocr, frames = ocr_frames(media, info["id"]) if media and media.suffix != ".m4a" else ([], [])
            record = {
                "id": vid,
                "source_url": url,
                "url": info.get("webpage_url") or url,
                "platform": info.get("extractor_key"),
                "uploader": info.get("uploader") or info.get("channel"),
                "upload_date": info.get("upload_date"),
                "duration": info.get("duration"),
                "description": info.get("description") or info.get("title") or "",
                "transcript": transcript,
                "ocr": ocr,
                "thumb": save_thumb(vid, thumb, frames),
                "llm": llm.read_listing(info.get("description") or info.get("title") or "", transcript, ocr, frames),
                "collected_at": time.strftime("%Y-%m-%d"),
            }
            (RAW / f"{vid}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1))
            errors.pop(url, None)
            new += 1
            print(f"[ok] {vid} ({len(transcript)} car. audio, {len(ocr)} lignes image)")
        except Exception as exc:
            e = errors.setdefault(url, {"tries": 0})
            e["tries"] += 1
            e["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            print(f"[échec] {url}: {exc}")
            traceback.print_exc()
        finally:
            shutil.rmtree(WORK, ignore_errors=True)

    ERRORS.write_text(json.dumps(errors, ensure_ascii=False, indent=1))
    print(f"{new} nouvelles annonces collectées")


if __name__ == "__main__":
    sys.exit(main())
