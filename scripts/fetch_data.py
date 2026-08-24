"""
Baja precio + fundamentals de Yahoo Finance para una lista de tickers,
calcula los ratios de valuación y escribe docs/data.json.

Corre en GitHub Actions (no necesitás Python local).
Para cambiar las empresas: editá la lista TICKERS de abajo.
"""

import json
import datetime
import yfinance as yf

# ─────────────────────────────────────────────────────────────
# EDITÁ ACÁ: agregá o sacá tickers de esta lista.
# ─────────────────────────────────────────────────────────────
TICKERS = ["AAPL", "MSFT", "JPM", "GOOGL", "NVDA", "KO"]
# ─────────────────────────────────────────────────────────────


def safe(d, *keys):
    """Devuelve el primer valor no nulo de una serie de claves posibles."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def ratios(info):
    price = safe(info, "currentPrice", "regularMarketPrice")
    shares = safe(info, "sharesOutstanding")
    mcap = safe(info, "marketCap")
    ebitda = safe(info, "ebitda")
    ni = safe(info, "netIncomeToCommon")
    equity = safe(info, "totalStockholderEquity")
    debt = safe(info, "totalDebt")
    cash = safe(info, "totalCash")
    revenue = safe(info, "totalRevenue")
    div_rate = safe(info, "dividendRate") or 0

    ev = None
    if mcap is not None:
        ev = mcap + (debt or 0) - (cash or 0)

    def div(a, b):
        return (a / b) if (a is not None and b) else None

    return {
        "ticker": info.get("symbol"),
        "name": safe(info, "shortName", "longName"),
        "sector": safe(info, "sector") or "—",
        "price": price,
        "marketCap": mcap,
        "pe": safe(info, "trailingPE"),
        "evEbitda": div(ev, ebitda),
        "pbv": safe(info, "priceToBook"),
        "roe": safe(info, "returnOnEquity"),
        "netMargin": safe(info, "profitMargins"),
        "netDebtEbitda": div((debt or 0) - (cash or 0), ebitda) if ebitda else None,
        "divYield": div(div_rate, price),
    }


def main():
    out = []
    for t in TICKERS:
        try:
            info = yf.Ticker(t).info
            r = ratios(info)
            if r["price"] is None:
                print(f"⚠  {t}: sin precio, se omite")
                continue
            out.append(r)
            print(f"✓  {t}: {r['name']}  ${r['price']}")
        except Exception as e:
            print(f"✗  {t}: {e}")

    payload = {
        "updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "companies": out,
    }
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nEscrito docs/data.json con {len(out)} empresas.")


if __name__ == "__main__":
    main()
