#!/usr/bin/env python3
"""
Monta o players.csv automaticamente a partir do clubs.csv usando o Wikidata.

Entrada : clubs.csv   (colunas: name,search[,qid])
            - name   : nome do clube (vira a pasta/coluna "team")
            - search : termo de busca no Wikidata (ex: "Real Madrid CF")
            - qid    : opcional, força o clube certo (ex: Q8682) se a busca errar
Saída   : players.csv (name,photo_url,wiki,team)

Só entram jogadores ATUAIS (vínculo com o clube sem data de término) e que
tenham foto cadastrada no Wikidata/Commons.
"""

import csv
import os
import sys
import time
from pathlib import Path

import requests

CLUBS_CSV = Path(os.getenv("CLUBS_CSV", "clubs.csv"))
OUT_CSV = Path(os.getenv("PLAYERS_CSV", "players.csv"))
WD_API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
TIMEOUT = 60
HEADERS = {
    "User-Agent": "PlayerCardBot/1.0 (projeto pessoal no GitHub Actions; requests)",
    "Accept": "application/sparql-results+json",
}
FOOTBALL_WORDS = ("futebol", "football", "soccer", "fútbol", "calcio")
BAD_WORDS = ("seleção", "national", "feminin", "women", "basquete", "basketball")


def get_json(url, params, retries=3):
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(3 * attempt)
    raise RuntimeError(str(last))


def resolve_club(term):
    """Procura o clube no Wikidata. Retorna (qid, label, descricao) ou None."""
    for lang in ("pt", "en"):
        data = get_json(WD_API, {
            "action": "wbsearchentities", "search": term, "language": lang,
            "uselang": lang, "type": "item", "limit": 10, "format": "json",
        })
        for item in data.get("search", []):
            desc = (item.get("description") or "").lower()
            if any(w in desc for w in FOOTBALL_WORDS) and not any(b in desc for b in BAD_WORDS):
                return item["id"], item.get("label", term), desc
    return None


def fetch_players(qid):
    query = f"""
    SELECT ?player ?playerLabel ?image WHERE {{
      ?player p:P54 ?st .
      ?st ps:P54 wd:{qid} .
      FILTER NOT EXISTS {{ ?st pq:P582 ?end }}
      ?player wdt:P106 wd:Q937857 ;
              wdt:P18 ?image .
      FILTER NOT EXISTS {{ ?player wdt:P570 ?died }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pt,en". }}
    }}
    """
    data = get_json(SPARQL, {"query": query, "format": "json"})
    rows = []
    for b in data["results"]["bindings"]:
        label = b["playerLabel"]["value"]
        if label.startswith("Q") and label[1:].isdigit():  # sem nome cadastrado
            continue
        image = b["image"]["value"].replace("http://", "https://")
        rows.append((b["player"]["value"].rsplit("/", 1)[-1], label, f"{image}?width=1200"))
    return rows


def main():
    if not CLUBS_CSV.exists():
        print(f"{CLUBS_CSV} não encontrado.")
        return 1

    with CLUBS_CSV.open(encoding="utf-8-sig", newline="") as f:
        clubs = list(csv.DictReader(f))

    seen = set()
    out_rows = []
    problems = []

    for c in clubs:
        team = (c.get("name") or "").strip()
        qid = (c.get("qid") or "").strip()
        term = (c.get("search") or team).strip()
        if not team:
            continue
        try:
            if not qid:
                found = resolve_club(term)
                if not found:
                    print(f"✗ {team}: clube não encontrado ({term!r}). Preencha a coluna qid.")
                    problems.append(team)
                    continue
                qid, label, desc = found
                print(f"• {team} -> {qid} ({label}; {desc})")
            players = fetch_players(qid)
        except Exception as e:
            print(f"✗ {team}: erro {e}")
            problems.append(team)
            continue

        added = 0
        for pid, label, url in players:
            if pid in seen:  # jogador emprestado/duplicado: fica no 1º clube
                continue
            seen.add(pid)
            out_rows.append([label, url, "", team])
            added += 1
        print(f"  {team}: {added} jogadores com foto")
        time.sleep(1.5)  # respeita o servidor

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
