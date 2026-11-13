"""
Baja fundamentals de EE.UU. y Argentina con yfinance y genera docs/data.json.

Para cada empresa calcula:
  - Múltiplos actuales (P/E TTM y forward, EV/EBITDA, P/BV, dividend yield, FCF yield)
  - Múltiplos históricos por cierre de ejercicio (lo que yfinance tenga, ~4-5 años)
  - Mediana, mínimo y máximo histórico de cada múltiplo
  - Una lectura "barata / en línea / cara" contra su propia historia
  - Serie de precios semanal del último año

Variables de entorno opcionales (las setea el workflow manual):
  AGREGAR="META, YPFD.BA"   QUITAR="KO"
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
TICKERS_FILE = ROOT / "tickers.json"
OUT_FILE = ROOT / "docs" / "data.json"

# Múltiplos donde "más bajo = más barato" y donde "más alto = más barato"
MENOR_ES_BARATO = ["pe", "ev_ebitda", "pbv"]
MAYOR_ES_BARATO = ["div_yield", "fcf_yield"]
UMBRAL = 0.15  # ±15% contra la mediana para cambiar de categoría


# ---------------------------------------------------------------- utilidades
def num(x):
    """Convierte a float válido o None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def positivo(x):
    """Múltiplos con denominador negativo (patrimonio o EBITDA < 0) no se comparan."""
    v = num(x)
    return v if v is not None and v > 0 else None


def fila(df, *nombres):
    """Devuelve la primera fila que exista en un estado contable de yfinance."""
    if df is None or df.empty:
        return None
    for n in nombres:
        if n in df.index:
            return df.loc[n]
    return None


def valor(serie, col):
    if serie is None or col not in serie.index:
        return None
    return num(serie[col])


def precio_al(hist, fecha):
    """Último cierre disponible a esa fecha o antes."""
    if hist is None or hist.empty:
        return None
    previo = hist.loc[:fecha]
    if previo.empty:
        return None
    return num(previo["Close"].iloc[-1])


def ratio(a, b, minimo_b=0):
    a, b = num(a), num(b)
    if a is None or b is None or b <= minimo_b:
        return None
    return a / b


def redondear(d, n=4):
    # "+ 0.0" convierte -0.0 en 0.0 para que no aparezca "-0,0%"
    return {k: (round(v, n) + 0.0 if isinstance(v, float) else v) for k, v in d.items()}


# ------------------------------------------------------------ lista tickers
def cargar_tickers():
    data = json.loads(TICKERS_FILE.read_text(encoding="utf-8"))
    data.setdefault("US", [])
    data.setdefault("AR", [])

    def partir(s):
        return [t.strip().upper() for t in (s or "").split(",") if t.strip()]

    agregar, quitar = partir(os.getenv("AGREGAR")), partir(os.getenv("QUITAR"))
    for t in agregar:
        mercado = "AR" if t.endswith(".BA") else "US"
        if t not in data[mercado]:
            data[mercado].append(t)
            print(f"+ agregado {t} a {mercado}")
    for t in quitar:
        for m in ("US", "AR"):
            if t in data[m]:
                data[m].remove(t)
                print(f"- quitado {t} de {m}")

    if agregar or quitar:
        TICKERS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


# --------------------------------------------------------------- históricos
def historico_multiplos(tk, hist, info):
    """Múltiplos al cierre de cada ejercicio fiscal disponible."""
    inc, bal, cf = tk.income_stmt, tk.balance_sheet, tk.cashflow
    if inc is None or inc.empty:
        return []

    eps = fila(inc, "Diluted EPS", "Basic EPS")
    ebitda = fila(inc, "EBITDA", "Normalized EBITDA")
    ventas = fila(inc, "Total Revenue", "Operating Revenue")
    neto = fila(inc, "Net Income", "Net Income Common Stockholders")
    deuda = fila(bal, "Total Debt")
    caja = fila(bal, "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments")
    pn = fila(bal, "Stockholders Equity", "Common Stock Equity")
    acciones = fila(bal, "Ordinary Shares Number", "Share Issued")
    fcf = fila(cf, "Free Cash Flow")

    divs = tk.dividends
    if divs is not None and not divs.empty and divs.index.tz is not None:
        divs.index = divs.index.tz_localize(None)

    filas = []
    for col in sorted(inc.columns):
        fecha = pd.Timestamp(col).tz_localize(None)
        p = precio_al(hist, fecha)
        if p is None:
            continue
        sh = valor(acciones, col) or num(info.get("sharesOutstanding"))
        mcap = p * sh if sh else None
        d, c = valor(deuda, col), valor(caja, col)
        ev = mcap + (d or 0) - (c or 0) if mcap else None
        div_12m = None
        if divs is not None and not divs.empty:
            ventana = divs[(divs.index > fecha - pd.Timedelta(days=365)) & (divs.index <= fecha)]
            div_12m = float(ventana.sum())

        filas.append(redondear({
            "anio": fecha.year,
            "fecha": fecha.strftime("%Y-%m-%d"),
            "precio": p,
            "eps": valor(eps, col),
            "ventas": valor(ventas, col),
            "ebitda": valor(ebitda, col),
            "neto": valor(neto, col),
            "deuda_neta": (d - c) if d is not None and c is not None else None,
            "pe": ratio(p, valor(eps, col)),
            "ev_ebitda": ratio(ev, valor(ebitda, col)),
            "pbv": ratio(mcap, valor(pn, col)),
            "div_yield": ratio(div_12m, p) if div_12m else 0.0,
            "fcf_yield": ratio(valor(fcf, col), mcap) if mcap else None,
        }))
    return filas


def resumen_historico(filas, actual):
    """Mediana/min/max por múltiplo y desvío del actual contra la mediana."""
    out = {}
    for m in MENOR_ES_BARATO + MAYOR_ES_BARATO:
        serie = [f[m] for f in filas if f.get(m) is not None]
        if m == "div_yield":
            serie = [v for v in serie if v > 0] or serie
        if len(serie) < 2:
            continue
        med = statistics.median(serie)
        act = actual.get(m)
        desvio = None
        if act is not None and med:
            desvio = act / med - 1
        out[m] = redondear({"mediana": med, "min": min(serie), "max": max(serie),
                            "n": len(serie), "desvio": desvio})
    return out


def lectura(resumen, actual):
    """Promedia cuán barata está contra su historia en cada múltiplo."""
    puntajes = []
    for m, r in resumen.items():
        act, med = actual.get(m), r["mediana"]
        if act is None or not med or act <= 0:
            continue
        if m in MENOR_ES_BARATO:
            puntajes.append(act / med - 1)       # negativo = barata
        else:
            puntajes.append(med / act - 1)       # yield alto = barata
    if not puntajes:
        return {"categoria": "sin_datos", "puntaje": None, "base": 0}
    # Cada múltiplo pesa como máximo ±100% y se usa la mediana, para que
    # un dato raro (un yield cerca de cero, un balance atípico) no domine.
    puntajes = [max(-1.0, min(1.0, x)) for x in puntajes]
    p = statistics.median(puntajes)
    cat = "barata" if p <= -UMBRAL else "cara" if p >= UMBRAL else "en_linea"
    return {"categoria": cat, "puntaje": round(p, 4), "base": len(puntajes)}


# ------------------------------------------------------------------ empresa
def procesar(sym, mercado):
    tk = yf.Ticker(sym)
    info = tk.info or {}
    hist = tk.history(period="6y", interval="1d", auto_adjust=False)
    if hist is not None and not hist.empty and hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)

    precio = num(info.get("currentPrice")) or num(info.get("regularMarketPrice"))
    if precio is None and hist is not None and not hist.empty:
        precio = num(hist["Close"].iloc[-1])
    previo = num(info.get("previousClose")) or num(info.get("regularMarketPreviousClose"))

    mcap = num(info.get("marketCap"))
    deuda, caja = num(info.get("totalDebt")), num(info.get("totalCash"))
    ebitda = num(info.get("ebitda"))
    fcf = num(info.get("freeCashflow"))
    div_tasa = num(info.get("trailingAnnualDividendRate")) or num(info.get("dividendRate"))

    actual = redondear({
        "pe": positivo(info.get("trailingPE")),
        "pe_fwd": positivo(info.get("forwardPE")),
        "ev_ebitda": positivo(info.get("enterpriseToEbitda")),
        "pbv": positivo(info.get("priceToBook")),
        "div_yield": ratio(div_tasa, precio) if div_tasa else 0.0,
        "fcf_yield": ratio(fcf, mcap),
    })

    moneda = info.get("currency")
    moneda_balance = info.get("financialCurrency") or moneda
    avisos = []
    filas = []
    if moneda and moneda_balance and moneda != moneda_balance:
        avisos.append(f"Precio en {moneda} y balances en {moneda_balance}: "
                      "no se calculan múltiplos históricos.")
    else:
        filas = historico_multiplos(tk, hist, info)
    if mercado == "AR":
        avisos.append("Balances en pesos nominales: con inflación alta, el histórico "
                      "de múltiplos es orientativo.")

    resumen = resumen_historico(filas, actual)

    semanal = []
    if hist is not None and not hist.empty:
        ult = hist.loc[hist.index >= hist.index[-1] - pd.Timedelta(days=365), "Close"]
        semanal = [[d.strftime("%Y-%m-%d"), round(float(v), 4)]
                   for d, v in ult.resample("W-FRI").last().dropna().items()]

    return {
        "ticker": sym,
        "mercado": mercado,
        "nombre": info.get("shortName") or info.get("longName") or sym,
        "sector": info.get("sector") or "Sin sector",
        "industria": info.get("industry"),
        "moneda": moneda,
        "precio": precio,
        "var_1d": ratio(precio - previo, previo) if precio and previo else None,
        "market_cap": mcap,
        "deuda_neta": (deuda - caja) if deuda is not None and caja is not None else None,
        "deuda_neta_ebitda": ratio((deuda or 0) - (caja or 0), ebitda) if ebitda else None,
        "crec_ventas": num(info.get("revenueGrowth")),
        "margen_ebitda": num(info.get("ebitdaMargins")),
        "margen_neto": num(info.get("profitMargins")),
        "roe": num(info.get("returnOnEquity")),
        "actual": actual,
        "historico": filas,
        "resumen": resumen,
        "lectura": lectura(resumen, actual),
        "precios_1a": semanal,
        "avisos": avisos,
    }


def main():
    tickers = cargar_tickers()
    empresas, errores = [], []
    for mercado in ("US", "AR"):
        for sym in tickers[mercado]:
            try:
                empresas.append(procesar(sym, mercado))
                print(f"ok  {sym}")
            except Exception as e:  # una empresa rota no frena al resto
                errores.append({"ticker": sym, "error": str(e)[:200]})
                print(f"ERR {sym}: {e}")

    OUT_FILE.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "umbral": UMBRAL,
        "empresas": empresas,
        "errores": errores,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n{len(empresas)} empresas, {len(errores)} errores -> {OUT_FILE}")


if __name__ == "__main__":
    main()
