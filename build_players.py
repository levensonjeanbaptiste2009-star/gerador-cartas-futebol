#!/usr/bin/env python3
"""
Monta o players.csv a partir do elenco ATUAL de cada clube na Wikipédia (inglês).

Entrada : clubs.csv   (colunas: name,wikipedia)
            - name      : nome do clube (vira a pasta/coluna "team")
            - wikipedia : título do artigo do clube na Wikipédia em inglês
Saída   : players.csv (name,photo_url,wiki,team)
            - name : nome que aparece na carta
            - wiki : título do artigo do jogador (o main.py pega a foto dele)

O script lê a seção "Current squad" / "First-team squad" do artigo do clube e
extrai os jogadores listados nela (elenco principal, inclusive emprestados).
"""

import csv
import os
import re
import sys
import time
from pathlib import Path

import requests

CLUBS_CSV = Path(os.getenv("CLUBS_CSV", "clubs.csv"))
OUT_CSV = Path(os.getenv("PLAYERS_CSV", "players.csv"))
WP_API = "https://en.wikipedia.org/w/api.php"
TIMEOUT = 40
MIN_PLAYERS = 8   # abaixo disso o resultado é considerado suspeito
HEADERS = {
    "User-Agent": "PlayerCardBot/1.0 (projeto pessoal no GitHub Actions; requests)",
}

SECTION_PATTERNS = [
    r"^(current )?(first[- ]team )?squad$",
    r"^(current )?first[- ]team( players)?$",
    r"^(current )?players$",
    r"squad|first[- ]team|elenco",
]
PLAYER_RE = re.compile(
    r"\{\{\s*(?:fs2?|football squad2?)[ _]player\b(.*?)\}\}", re.I | re.S
)
NAME_RE = re.compile(r"\|\s*name\s*=\s*(\[\[[^\]]+\]\]|[^|}]+)", re.I)
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
TEMPLATE_RE = re.compile(r"\{\{\s*([^{}|]*squad[^{}|]*?)\s*\}\}", re.I)


def api(params, retries=3):
    params = {**params, "format": "json", "formatversion": 2}
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(WP_API, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"].get("info", "erro da API"))
            return data
        except (requests.RequestException, ValueError, RuntimeError) as e:
            last = e
            time.sleep(2 * attempt)
    raise RuntimeError(str(last))


def clean_title(title):
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def find_section(page):
    data = api({"action": "parse", "page": page, "prop": "sections", "redirects": 1})
    sections = data["parse"]["sections"]
    for pattern in SECTION_PATTERNS:
        for s in sections:
            line = re.sub(r"<[^>]+>", "", s["line"]).strip().lower()
            if re.search(pattern, line):
                return s["index"], line
    return None, None


def wikitext(page, section=None):
    params = {"action": "parse", "page": page, "prop": "wikitext", "redirects": 1}
    if section:
        params["section"] = section
    wt = api(params)["parse"]["wikitext"]
    return wt["*"] if isinstance(wt, dict) else wt


def extract_players(text):
    players = []
    for m in PLAYER_RE.finditer(text):
        nm = NAME_RE.search(m.group(1))
        if not nm:
            continue
        raw = nm.group(1).strip()
        link = LINK_RE.match(raw)
        if link:
            target = link.group(1).strip()
            if target.lower().startswith(("file:", "image:")):
                continue
            display = clean_title((link.group(2) or target).strip())
            players.append((display, target))
        elif raw:
            players.append((clean_title(raw), ""))  # sem link: o main.py busca pelo nome
    return players


def squad_for(page):
    """Retorna (lista de (nome, titulo_wiki), descricao_da_fonte)."""
    idx, line = find_section(page)
    if not idx:
        return [], "seção de elenco não encontrada"
    text = wikitext(page, idx)
    players = extract_players(text)
    source = f"seção '{line}'"
    if len(players) < MIN_PLAYERS:
        # alguns clubes guardam o elenco em um modelo separado (Template:... squad)
        for t in TEMPLATE_RE.findall(text):
            try:
                more = extract_players(wikitext("Template:" + t.strip()))
            except Exception:
                continue
            if len(more) > len(players):
                players, source = more, f"modelo '{t.strip()}'"
    return players, source


def main():
    if not CLUBS_CSV.exists():
        print(f"{CLUBS_CSV} não encontrado.")
        return 1

    with CLUBS_CSV.open(encoding="utf-8-sig", newline="") as f:
        clubs = list(csv.DictReader(f))

    out_rows, problems, seen = [], [], set()

    for c in clubs:
        team = (c.get("name") or "").strip()
        page = (c.get("wikipedia") or c.get("search") or team).strip()
        if not team:
            continue
        try:
            players, source = squad_for(page)
        except Exception as e:
            print(f"✗ {team}: erro ao ler '{page}' ({e})")
            problems.append(team)
            continue

        if len(players) < MIN_PLAYERS:
            print(f"✗ {team}: só {len(players)} jogadores em '{page}' ({source}). "
                  f"Confira o título em clubs.csv.")
            problems.append(team)
            if not players:
                continue

        added = []
        for display, target in players:
            key = (target or display).lower()
            if key in seen:  # jogador repetido: fica no 1º clube
                continue
            seen.add(key)
            out_rows.append([display, "", target, team])
            added.append(display)
        print(f"✓ {team}: {len(added)} jogadores [{source}] (ex.: {', '.join(added[:5])})")
        time.sleep(1)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "photo_url", "wiki", "team"])
        w.writerows(out_rows)

    print(f"\n{len(out_rows)} jogadores gravados em {OUT_CSV}.")
    if problems:
        print("Clubes com problema:", ", ".join(problems))
    return 0 if out_rows else 1


if __name__ == "__main__":
    sys.exit(main())
