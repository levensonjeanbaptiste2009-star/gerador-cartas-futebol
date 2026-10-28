#!/usr/bin/env python3
"""
Gera cartas de jogadores: baixa a foto, remove o fundo (PNG transparente),
recorta ao redor do jogador e escreve o nome de forma estilizada.

Entrada : players.csv  (colunas: name,photo_url[,team])
Saída   : output/<nome>.png
"""

import csv
import io
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from rembg import new_session, remove

# ----------------------------- CONFIGURAÇÃO -----------------------------
INPUT_CSV = Path(os.getenv("INPUT_CSV", "players.csv"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
FORCE = os.getenv("FORCE", "false").lower() == "true"  # refaz mesmo se já existir
CARD_WIDTH = 700                 # largura final da carta (px)
PADDING = 20                     # margem ao redor do jogador após o recorte
REMBG_MODEL = os.getenv("REMBG_MODEL", "isnet-general-use")  # ou "u2net"
REQUEST_TIMEOUT = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PlayerCardBot/1.0; +https://github.com)"
}

FONT_CANDIDATES = [
    "fonts/font.ttf",  # coloque sua fonte aqui para sobrescrever
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
# ------------------------------------------------------------------------


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "jogador"


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    print("  ! Nenhuma fonte TTF encontrada, usando fonte padrão (sem estilo).")
    return ImageFont.load_default()


def download_image(url: str, retries: int = 3) -> bytes:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 * attempt)
    raise RuntimeError(f"falha ao baixar {url}: {last_err}")


def cut_out(raw: bytes, session) -> Image.Image:
    """Remove o fundo e recorta ao redor do jogador."""
    src = Image.open(io.BytesIO(raw)).convert("RGBA")
    result = remove(src, session=session)  # RGBA com fundo transparente
    bbox = result.getchannel("A").point(lambda a: 255 if a > 10 else 0).getbbox()
    if not bbox:
        raise RuntimeError("não foi possível detectar o jogador na imagem")
    result = result.crop(bbox)

    # margem transparente
    canvas = Image.new(
        "RGBA",
        (result.width + 2 * PADDING, result.height + 2 * PADDING),
        (0, 0, 0, 0),
    )
    canvas.paste(result, (PADDING, PADDING), result)

    # redimensiona para largura padrão da carta
    ratio = CARD_WIDTH / canvas.width
    return canvas.resize((CARD_WIDTH, int(canvas.height * ratio)), Image.LANCZOS)


def gold_gradient(size, top=(255, 236, 140), bottom=(201, 144, 20)) -> Image.Image:
    w, h = size
    grad = Image.new("RGBA", size)
    px = grad.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(w):
            px[x, y] = color
    return grad


def add_name(card: Image.Image, name: str) -> Image.Image:
    """Escreve o nome (maiúsculo, dourado, contorno e sombra) na base da carta."""
    text = name.upper()
    max_w = int(card.width * 0.90)

    # ajusta o tamanho da fonte para caber na largura
    size = 110
    font = load_font(size)
    while size > 20:
        font = load_font(size)
        l, t, r, b = font.getbbox(text)
        if (r - l) <= max_w:
            break
        size -= 4

    stroke = max(3, size // 14)
    l, t, r, b = font.getbbox(text, stroke_width=stroke)
    tw, th = r - l, b - t

    # máscara do texto
    mask = Image.new("L", (tw + 2 * stroke, th + 2 * stroke), 0)
    ImageDraw.Draw(mask).text((stroke - l, stroke - t), text, font=font, fill=255)

    # contorno preto
    outline_mask = Image.new("L", mask.size, 0)
    ImageDraw.Draw(outline_mask).text(
        (stroke - l, stroke - t), text, font=font, fill=255,
        stroke_width=stroke, stroke_fill=255,
    )

    x = (card.width - mask.width) // 2
    y = card.height - mask.height - 25

    layer = Image.new("RGBA", card.size, (0, 0, 0, 0))

    # sombra
    shadow = Image.new("RGBA", mask.size, (0, 0, 0, 170))
    shadow.putalpha(outline_mask.filter(ImageFilter.GaussianBlur(6)))
    layer.alpha_composite(shadow, (x + 4, y + 6))

    # contorno
    outline = Image.new("RGBA", mask.size, (15, 15, 15, 255))
    outline.putalpha(outline_mask)
    layer.alpha_composite(outline, (x, y))

    # preenchimento dourado
    fill = gold_gradient(mask.size)
    fill.putalpha(mask)
    layer.alpha_composite(fill, (x, y))

    return Image.alpha_composite(card, layer)


def main() -> int:
    if not INPUT_CSV.exists():
        print(f"Arquivo {INPUT_CSV} não encontrado.")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    session = new_session(REMBG_MODEL)

    ok, skipped, failed = 0, 0, []

    with INPUT_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    print(f"{len(rows)} jogadores na lista.")

    for i, row in enumerate(rows, 1):
        name = (row.get("name") or "").strip()
        url = (row.get("photo_url") or "").strip()
        if not name or not url:
            print(f"[{i}] linha inválida, ignorada: {row}")
            continue

        out_path = OUTPUT_DIR / f"{slugify(name)}.png"
        if out_path.exists() and not FORCE:
            print(f"[{i}] {name}: já existe, pulando.")
            skipped += 1
            continue

        print(f"[{i}] {name}: processando...")
        try:
            raw = download_image(url)
            card = cut_out(raw, session)
            card = add_name(card, name)
            card.save(out_path, "PNG", optimize=True)
            ok += 1
        except Exception as e:  # um jogador com erro não derruba o lote
            print(f"  ✗ erro: {e}")
            failed.append(name)

    print(f"\nConcluído: {ok} gerados, {skipped} pulados, {len(failed)} com erro.")
    if failed:
        print("Falharam:", ", ".join(failed))
    # só falha o job se nada funcionou
    return 1 if (failed and ok == 0 and skipped == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
