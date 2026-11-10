"""Gera o index.html do GIS-Painel a partir dos estudos existentes em C:\\Pipelines.

Uso:  python gerar_painel.py
Varre Estudo-APS/estudos, Estudo-MAC/powerbi/projects e SUS-Estabelecimentos/powerbi/projects,
lê cada estudo.json (e project.json no hospitalar) e embute os dados em template.html -> index.html.
"""
from __future__ import annotations

import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PIPE = Path(r"C:\Pipelines")
TRATADOS = PIPE / "Dados-SUS" / "tratados"
VENV_PY = PIPE / "Estudo-MAC" / ".venv" / "Scripts" / "python.exe"

try:  # o Python do sistema não tem pyarrow: reexecuta com o venv do Estudo-MAC
    import pyarrow  # noqa: F401
except ImportError:
    import subprocess
    import sys
    raise SystemExit(subprocess.call([str(VENV_PY), "-I", str(Path(__file__).resolve()), *sys.argv[1:]]))


def ler(caminho: Path) -> dict:
    if not caminho.is_file():
        return {}
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return json.loads(caminho.read_text(encoding=enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return {}


def dia(texto: str | None) -> str | None:
    return texto[:10] if texto else None


def periodo_real(pasta: Path) -> str | None:
    """Primeira e última competência com produção em producao_consolidada.parquet (dados reais, não a janela pedida)."""
    arquivo = pasta / "producao_consolidada.parquet"
    if not arquivo.is_file():
        return None
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    arq = pq.ParquetFile(arquivo)
    coluna = arq.read(columns=[arq.schema_arrow.names[0]]).column(0)
    limites = pc.min_max(coluna).as_py()
    if limites["min"] is None:
        return None

    def aaaamm(v) -> str:
        return v.strftime("%Y%m") if hasattr(v, "strftime") else str(v)[:6].replace("-", "")

    return f'{aaaamm(limites["min"])} a {aaaamm(limites["max"])}'


def aps() -> list[dict]:
    saida = []
    for pasta in sorted((PIPE / "Estudo-APS" / "estudos").glob("*/")):
        e = ler(pasta / "estudo.json")
        if not e:
            continue
        ibge6 = str(e.get("municipio", ""))[:6]
        j = e.get("janela") or []
        saida.append({
            "id": f"aps-{ibge6}", "titulo": e.get("nome", pasta.name), "uf": e.get("uf", ""), "ibge": ibge6,
            "subtitulo": f'{e.get("nome", "")} · {e.get("uf", "")}',
            "periodo": f"{j[0]} a {j[1]}" if len(j) == 2 else None,
            "gerado": dia(e.get("estudo_gerado_em")), "publicado": dia((e.get("publicado") or {}).get("em")),
            "link": e.get("link_publico"), "relatorio": e.get("relatorio"),
        })
    return saida


def mac() -> list[dict]:
    saida = []
    for pasta in sorted((PIPE / "Estudo-MAC" / "powerbi" / "projects").glob("*/")):
        e = ler(pasta / "estudo.json")
        if not e:
            continue
        saida.append({
            "id": f'mac-{e.get("ibge")}', "titulo": e.get("municipio", pasta.name), "uf": e.get("uf", ""), "ibge": e.get("ibge"),
            "subtitulo": f'{e.get("municipio", "")} · {e.get("uf", "")}',
            "detalhe": f'{len(e.get("estabelecimentos", []))} estabelecimentos',
            "periodo": periodo_real(TRATADOS / "mac" / e.get("estudo_id", "")),
            "gerado": dia(e.get("estudo_gerado_em")), "publicado": dia((e.get("publicado") or {}).get("em")),
            "link": e.get("link_publico"), "relatorio": e.get("relatorio"),
        })
    return saida


def hospitalar(municipios: dict[str, str]) -> list[dict]:
    saida = []
    for pasta in sorted((PIPE / "SUS-Estabelecimentos" / "powerbi" / "projects").glob("*/")):
        p, e = ler(pasta / "project.json"), ler(pasta / "estudo.json")
        if not p and not e:
            continue
        cnes = p.get("cnes", pasta.name)
        nome = (p.get("name") or p.get("estabelecimento") or f"CNES {cnes}").title()
        ibge6 = str(p.get("municipality_code", ""))[:6]
        uf = p.get("state") or ""
        cidade = municipios.get(ibge6, "")
        saida.append({
            "id": f"hosp-{cnes}", "titulo": nome, "uf": uf, "ibge": ibge6 or None,
            "subtitulo": " · ".join(x for x in (cidade, uf, f"CNES {cnes}") if x),
            "periodo": periodo_real(TRATADOS / "hospitalar" / str(cnes)),
            "gerado": None, "publicado": dia((e.get("publicado") or {}).get("em")),
            "link": e.get("link_publico"), "relatorio": None,
        })
    return saida


def main() -> None:
    a, m = aps(), mac()
    municipios = {x["ibge"]: x["titulo"] for x in a + m if x.get("ibge")}
    h = hospitalar(municipios)
    dados = {
        "gerado_em": __import__("datetime").datetime.now().strftime("%d/%m/%Y %H:%M"),
        "tipos": [
            {"id": "aps", "nome": "Atenção Primária", "sigla": "APS",
             "descricao": "Cobertura, equipes, produção e financiamento da APS municipal.", "estudos": a},
            {"id": "mac", "nome": "Média e Alta Complexidade", "sigla": "MAC",
             "descricao": "Teto, repasses e produção ambulatorial e hospitalar do município.", "estudos": m},
            {"id": "hosp", "nome": "Estabelecimentos", "sigla": "HOSP",
             "descricao": "Diagnóstico individual de hospitais e unidades de saúde (CNES).", "estudos": h},
        ],
    }
    html = (AQUI / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DADOS__*/null", json.dumps(dados, ensure_ascii=False))
    (AQUI / "index.html").write_text(html, encoding="utf-8")
    for t in dados["tipos"]:
        com_bi = sum(1 for x in t["estudos"] if x["link"])
        print(f'{t["sigla"]}: {len(t["estudos"])} estudos, {com_bi} com BI')


if __name__ == "__main__":
    main()
