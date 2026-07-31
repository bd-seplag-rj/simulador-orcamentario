"""
focus.py — Busca as expectativas mais recentes do Boletim Focus (BCB).

Fonte: API pública Olinda/BCB — Expectativas de Mercado Anuais (sem autenticação).
Usada para pré-preencher os drivers macro SEMPRE com o Focus mais recente.

Mapeia os indicadores do Focus para os drivers do simulador. Brent e produção
de óleo NÃO vêm do Focus (ver botão de projeção de royalties no painel).

Robusto por design: em caso de falha de rede, cai no fallback (âncoras do
config, do PLDO) e sinaliza `ok=False` para o painel avisar o usuário.
"""
from __future__ import annotations
import json
import ssl
import urllib.parse
import urllib.request
from datetime import date

from . import config as C

_BASE = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/"
         "odata/ExpectativasMercadoAnuais")

# driver do simulador -> nome do indicador no Focus
INDICADORES = {
    "pib_real": "PIB Total",
    "ipca": "IPCA",
    "selic": "Selic",
    "cambio": "Câmbio",
    "igpm": "IGP-M",
}


def _fetch_indicador(indicador: str, anos: list[int], timeout: int = 15) -> dict:
    """Retorna {ano: (mediana, data_str)} para o indicador, base de cálculo 0
    (últimos 30 dias — a base padrão do Focus), pegando a data mais recente."""
    lo, hi = min(anos), max(anos)
    filtro = (f"Indicador eq '{indicador}' and DataReferencia ge '{lo}' "
              f"and DataReferencia le '{hi}' and baseCalculo eq 0")
    params = {
        "$filter": filtro,
        "$orderby": "Data desc",
        "$top": "200",
        "$format": "json",
        "$select": "Indicador,Data,DataReferencia,Mediana",
    }
    url = _BASE + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, headers={"User-Agent": "simulador-erj/1.0"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        data = json.load(resp)
    out = {}
    for row in data.get("value", []):
        ano = int(row["DataReferencia"])
        if ano in anos and ano not in out:   # ordenado por Data desc => 1º = mais recente
            out[ano] = (float(row["Mediana"]), row["Data"])
    return out


def ultimo_focus(anos: list[int] = None) -> dict:
    """Busca o Focus mais recente para todos os drivers mapeados.

    Retorna:
      {
        "valores": {driver: {ano: valor}},   # inclui fallback p/ o que falhar
        "data_ref": "YYYY-MM-DD" | None,      # data do boletim mais recente obtido
        "ok": bool,                            # True se buscou tudo online
        "origem": {driver: "focus"|"fallback"},
        "erro": str | None,
      }
    """
    anos = anos or C.ANOS
    valores, origem = {}, {}
    datas = []
    erro = None
    ok = True
    for driver, indicador in INDICADORES.items():
        try:
            res = _fetch_indicador(indicador, anos)
            if res and all(a in res for a in anos):
                valores[driver] = {a: round(res[a][0], 2) for a in anos}
                datas.extend(res[a][1] for a in anos)
                origem[driver] = "focus"
                continue
            raise ValueError("resposta incompleta")
        except Exception as e:  # noqa: BLE001
            ok = False
            erro = f"{type(e).__name__}: {e}"
            valores[driver] = dict(C.DRIVERS_MACRO[driver]["ancora"])
            origem[driver] = "fallback"
    # drivers fora do Focus (Brent, produção) sempre vêm do config
    for driver in C.DRIVERS_MACRO:
        if driver not in valores:
            valores[driver] = dict(C.DRIVERS_MACRO[driver]["ancora"])
            origem[driver] = "fallback"
    data_ref = max(datas)[:10] if datas else None
    return {"valores": valores, "data_ref": data_ref, "ok": ok,
            "origem": origem, "erro": erro,
            "consultado_em": date.today().isoformat()}
