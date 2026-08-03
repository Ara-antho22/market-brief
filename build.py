"""
Daily Market Brief — fetches market data, generates summaries, writes index.html

Runs once per weekday morning via GitHub Actions.
API keys are read from environment variables (GitHub Secrets), never hardcoded.
"""

import os
import json
import html
from datetime import datetime, timedelta, timezone

import requests

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "")
FRED_KEY = os.environ.get("FRED_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

ANTHROPIC_MODEL = "claude-sonnet-5"

ET = timezone(timedelta(hours=-4))  # Eastern Daylight Time
TODAY = datetime.now(ET)

# Series pulled from FRED (authoritative, free, no rate limit).
FRED_SERIES = {
    "sp500":        ("SP500",        "level",   2),
    "nasdaq":       ("NASDAQCOM",    "level",   2),
    "dow":          ("DJIA",         "level",   2),
    "nikkei":       ("NIKKEI225",    "level",   2),
    "wti":          ("DCOILWTICO",   "level",   2),
    "vix":          ("VIXCLS",       "level",   2),
    "dxy":          ("DTWEXBGS",     "level",   2),
    "ust10":        ("DGS10",        "pct",     2),
    "ust2":         ("DGS2",         "pct",     2),
    "sofr":         ("SOFR",         "pct",     2),
    "unemployment": ("UNRATE",       "pct",     1),
    "cpi_index":    ("CPIAUCSL",     "level",   2),
    "hy_oas":       ("BAMLH0A0HYM2", "pct",     2),
    "ig_oas":       ("BAMLC0A0CM",   "pct",     2),
}

# Finnhub ETF proxies where FRED has no daily coverage.
FINNHUB_PROXIES = {
    "russell":   ("IWM",  "iShares Russell 2000 ETF"),
    "ftse":      ("EWU",  "iShares MSCI United Kingdom ETF"),
    "eurostoxx": ("FEZ",  "SPDR EURO STOXX 50 ETF"),
    "shanghai":  ("ASHR", "Xtrackers Harvest CSI 300 ETF"),
    "frontier":  ("FM",   "iShares MSCI Frontier & Select EM ETF"),
    "gold":      ("GLD",  "SPDR Gold Shares ETF"),
    "hyg":       ("HYG",  "iShares iBoxx High Yield Corporate Bond ETF"),
}

# Sector coverage. Each gets its own news pull, its own entry, and its own sector
# ETF so the write-up can reference how the sector actually traded.
SECTORS = [
    {
        "key": "energy",
        "name": "Energy",
        "etf": "XLE",
        "query": "oil prices OR OPEC OR natural gas OR refiners OR energy stocks",
    },
    {
        "key": "tech",
        "name": "Technology",
        "etf": "XLK",
        "query": "semiconductors OR software stocks OR cloud computing OR AI capex",
    },
    {
        "key": "healthcare",
        "name": "Health Care",
        "etf": "XLV",
        "query": "pharmaceutical OR biotech OR health insurers OR FDA approval",
    },
    {
        "key": "industrials",
        "name": "Industrials",
        "etf": "XLI",
        "query": "industrial stocks OR aerospace OR machinery OR freight OR defense contractors",
    },
    {
        "key": "realestate",
        "name": "Real Estate",
        "etf": "XLRE",
        "query": "REIT OR commercial real estate OR mortgage rates OR office vacancy",
    },
    {
        "key": "discretionary",
        "name": "Consumer Discretionary",
        "etf": "XLY",
        "query": "retail sales OR consumer spending OR restaurants OR autos OR travel demand",
    },
    {
        "key": "staples",
        "name": "Consumer Staples",
        "etf": "XLP",
        "query": "consumer staples OR packaged food OR beverage companies OR grocery prices",
    },
]

MACRO_TOPICS = {
    "fed": "federal reserve OR FOMC OR interest rate decision OR Powell",
    "inflation": "inflation OR CPI OR PCE OR producer prices",
    "labor": "jobs report OR unemployment claims OR payrolls OR wage growth",
    "credit": "leveraged loans OR high yield bonds OR corporate credit OR debt issuance",
    "global": "treasury yields OR dollar OR trade policy OR tariffs OR global growth",
}

# World and geopolitical news. This is the pool "Moving the Market" draws from, kept
# deliberately separate from sector coverage so the section stays big-picture.
WORLD_TOPICS = {
    "conflict": "war OR military conflict OR geopolitical crisis OR ceasefire",
    "trade": "sanctions OR tariffs OR trade war OR export controls",
    "politics": "election OR government shutdown OR political crisis OR coup",
    "global_econ": "China economy OR global growth OR IMF OR sovereign debt crisis",
    "supply": "oil supply disruption OR shipping route OR strait OR supply chain crisis",
}

# Curated large caps used to filter the earnings calendar down to names worth knowing.
LARGE_CAPS = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "GOOG": "Alphabet", "META": "Meta Platforms",
    "TSLA": "Tesla", "AVGO": "Broadcom", "BRK.B": "Berkshire Hathaway",
    "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard", "LLY": "Eli Lilly",
    "UNH": "UnitedHealth", "XOM": "Exxon Mobil", "CVX": "Chevron",
    "JNJ": "Johnson & Johnson", "WMT": "Walmart", "PG": "Procter & Gamble",
    "HD": "Home Depot", "COST": "Costco", "ABBV": "AbbVie", "MRK": "Merck",
    "PEP": "PepsiCo", "KO": "Coca-Cola", "BAC": "Bank of America", "CRM": "Salesforce",
    "ORCL": "Oracle", "AMD": "AMD", "NFLX": "Netflix", "ADBE": "Adobe", "CSCO": "Cisco",
    "MCD": "McDonald's", "TMO": "Thermo Fisher", "ABT": "Abbott", "DHR": "Danaher",
    "PFE": "Pfizer", "WFC": "Wells Fargo", "GS": "Goldman Sachs", "MS": "Morgan Stanley",
    "C": "Citigroup", "BLK": "BlackRock", "SCHW": "Charles Schwab",
    "AXP": "American Express", "CAT": "Caterpillar", "DE": "Deere", "BA": "Boeing",
    "HON": "Honeywell", "GE": "GE Aerospace", "LMT": "Lockheed Martin", "RTX": "RTX",
    "UPS": "UPS", "UNP": "Union Pacific", "MMM": "3M", "EMR": "Emerson Electric",
    "ETN": "Eaton", "NKE": "Nike", "SBUX": "Starbucks", "TGT": "Target", "LOW": "Lowe's",
    "BKNG": "Booking Holdings", "MAR": "Marriott", "GM": "General Motors", "F": "Ford",
    "TJX": "TJX Companies", "CMG": "Chipotle", "DIS": "Disney",
    "PM": "Philip Morris", "MO": "Altria", "MDLZ": "Mondelez",
    "CL": "Colgate-Palmolive", "KMB": "Kimberly-Clark", "GIS": "General Mills",
    "KHC": "Kraft Heinz", "STZ": "Constellation Brands", "SYY": "Sysco", "KR": "Kroger",
    "HSY": "Hershey", "K": "Kellanova", "COP": "ConocoPhillips", "SLB": "SLB",
    "EOG": "EOG Resources", "PSX": "Phillips 66", "MPC": "Marathon Petroleum",
    "VLO": "Valero", "OXY": "Occidental", "HAL": "Halliburton", "KMI": "Kinder Morgan",
    "WMB": "Williams Companies", "OKE": "ONEOK", "AMT": "American Tower",
    "PLD": "Prologis", "EQIX": "Equinix", "SPG": "Simon Property", "O": "Realty Income",
    "WELL": "Welltower", "PSA": "Public Storage", "CCI": "Crown Castle",
    "DLR": "Digital Realty", "VICI": "VICI Properties", "AVB": "AvalonBay",
    "CVS": "CVS Health", "CI": "Cigna", "ELV": "Elevance Health", "HUM": "Humana",
    "MCK": "McKesson", "AMGN": "Amgen", "GILD": "Gilead",
    "BMY": "Bristol Myers Squibb", "VRTX": "Vertex", "REGN": "Regeneron",
    "ISRG": "Intuitive Surgical", "SYK": "Stryker", "BSX": "Boston Scientific",
    "MDT": "Medtronic", "ZTS": "Zoetis", "INTC": "Intel", "QCOM": "Qualcomm",
    "TXN": "Texas Instruments", "MU": "Micron", "AMAT": "Applied Materials",
    "LRCX": "Lam Research", "KLAC": "KLA", "ADI": "Analog Devices",
    "NOW": "ServiceNow", "INTU": "Intuit", "IBM": "IBM", "UBER": "Uber",
    "SHOP": "Shopify", "PANW": "Palo Alto Networks", "SNOW": "Snowflake",
    "PLTR": "Palantir", "ANET": "Arista Networks", "NEE": "NextEra Energy",
    "DUK": "Duke Energy", "SO": "Southern Company", "D": "Dominion Energy",
    "LIN": "Linde", "APD": "Air Products", "SHW": "Sherwin-Williams",
    "FCX": "Freeport-McMoRan", "NUE": "Nucor", "DOW": "Dow Inc", "T": "AT&T",
    "VZ": "Verizon", "TMUS": "T-Mobile", "CMCSA": "Comcast", "DAL": "Delta Air Lines",
    "UAL": "United Airlines", "LUV": "Southwest Airlines",
}


# ----------------------------------------------------------------------------
# Data fetching
# ----------------------------------------------------------------------------

def fred_observations(series_id, limit=400):
    """Return list of (date, value) for a FRED series, newest first."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    rows = []
    for obs in r.json().get("observations", []):
        if obs["value"] in (".", "", None):
            continue
        rows.append((obs["date"], float(obs["value"])))
    return rows


def fetch_fred_all():
    """Fetch every FRED series; return dict of key -> quote dict."""
    out = {}
    for key, (series_id, unit, dec) in FRED_SERIES.items():
        try:
            rows = fred_observations(series_id)
            if len(rows) < 2:
                continue
            (d0, v0), (_, v1) = rows[0], rows[1]
            out[key] = {
                "value": v0,
                "prev": v1,
                "date": d0,
                "pct_change": ((v0 - v1) / v1 * 100) if v1 else 0.0,
                "abs_change": v0 - v1,
                "unit": unit,
                "decimals": dec,
                "series_id": series_id,
            }
            if key == "cpi_index":
                yr, mo = d0[:4], d0[5:7]
                for d, v in rows:
                    if d[5:7] == mo and int(yr) - int(d[:4]) == 1:
                        out[key]["yoy"] = (v0 - v) / v * 100
                        break
        except Exception as e:
            print(f"  ! FRED {series_id} failed: {e}")
    return out


def finnhub_quote(symbol):
    r = requests.get(
        "https://finnhub.io/api/v1/quote",
        params={"symbol": symbol, "token": FINNHUB_KEY},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def fetch_finnhub_all():
    """Fetch ETF proxy quotes plus the seven sector ETFs."""
    out = {}
    targets = dict(FINNHUB_PROXIES)
    for s in SECTORS:
        targets[f"sector_{s['key']}"] = (s["etf"], f"{s['name']} Select Sector SPDR")

    for key, (symbol, longname) in targets.items():
        try:
            q = finnhub_quote(symbol)
            if not q.get("c"):
                continue
            out[key] = {
                "value": q["c"],
                "prev": q.get("pc", q["c"]),
                "pct_change": q.get("dp", 0.0) or 0.0,
                "abs_change": q.get("d", 0.0) or 0.0,
                "symbol": symbol,
                "longname": longname,
                "decimals": 2,
                "unit": "level",
            }
        except Exception as e:
            print(f"  ! Finnhub {symbol} failed: {e}")
    return out


def fetch_earnings_calendar():
    """Pull the coming week's earnings, filtered to names worth knowing."""
    start = TODAY.strftime("%Y-%m-%d")
    end = (TODAY + timedelta(days=8)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": start, "to": end, "token": FINNHUB_KEY},
            timeout=25,
        )
        r.raise_for_status()
        rows = r.json().get("earningsCalendar", [])
    except Exception as e:
        print(f"  ! Earnings calendar failed: {e}")
        return []

    keep = []
    for row in rows:
        sym = (row.get("symbol") or "").upper()
        if sym not in LARGE_CAPS:
            continue
        keep.append({
            "date": row.get("date", ""),
            "symbol": sym,
            "name": LARGE_CAPS[sym],
            "hour": (row.get("hour") or "").lower(),
            "eps_est": row.get("epsEstimate"),
        })

    keep.sort(key=lambda x: (x["date"], x["symbol"]))
    seen, deduped = set(), []
    for k in keep:
        if k["symbol"] in seen:
            continue
        seen.add(k["symbol"])
        deduped.append(k)
    return deduped


def parse_rss(xml_text, tag_label, limit=10):
    """Parse a Google News RSS feed into article dicts."""
    import re as _re
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  ! RSS parse failed for {tag_label}: {e}")
        return []

    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue

        src_el = item.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        # Google appends " - Publisher" to the headline; strip it once we have the name
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()

        desc = _re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        desc = html.unescape(desc)
        desc = _re.sub(r"<[^>]+>", " ", desc)
        desc = _re.sub(r"\s+", " ", desc).strip()

        published = ""
        raw = item.findtext("pubDate") or ""
        if raw:
            try:
                published = datetime.strptime(
                    raw, "%a, %d %b %Y %H:%M:%S %Z"
                ).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                try:
                    published = datetime.strptime(
                        raw, "%a, %d %b %Y %H:%M:%S %z"
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    published = ""

        out.append({
            "title": title,
            "source": source or "Google News",
            "url": link,
            "desc": desc[:400],
            "published": published,
        })
        if len(out) >= limit:
            break
    return out


def news_for(query, limit=10):
    """Live headlines for a query via Google News RSS. No key, no delay."""
    try:
        r = requests.get(
            "https://news.google.com/rss/search",
            params={"q": f"{query} when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; market-brief/1.0)"},
            timeout=25,
        )
        r.raise_for_status()
        return parse_rss(r.text, query[:30], limit)
    except Exception as e:
        print(f"  ! Google News failed ({query[:30]}...): {e}")
        return []


def fetch_finnhub_news(limit=25):
    """Finnhub's curated general market news. Free tier, current."""
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_KEY},
            timeout=20,
        )
        r.raise_for_status()
        out = []
        for a in r.json()[:limit]:
            ts = a.get("datetime")
            published = ""
            if ts:
                published = datetime.fromtimestamp(ts, timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            out.append({
                "title": (a.get("headline") or "").strip(),
                "source": a.get("source", "") or "Finnhub",
                "url": a.get("url", ""),
                "desc": (a.get("summary") or "")[:400],
                "published": published,
            })
        return [a for a in out if a["title"] and a["url"]]
    except Exception as e:
        print(f"  ! Finnhub news failed: {e}")
        return []


def headlines_blob(articles, limit=8):
    out = ""
    for a in articles[:limit]:
        out += f"- {a['title']} [{a['source']}] {a['url']}\n  {a['desc']}\n"
    return out or "- (no headlines returned)\n"


# ----------------------------------------------------------------------------
# AI generation
# ----------------------------------------------------------------------------

VOICE = """You are writing the morning edition of a personal equity research newsletter \
for a first-year leveraged finance analyst at a bulge-bracket bank. She reads it on her \
commute before the desk opens. She has a finance degree and does not need terms defined. \
She wants precision and mechanism, not filler.

Style rules that apply to everything you write:
- No throat-clearing. Never open with "markets were mixed" or "investors weighed."
- Every factual claim must trace to a headline or data point provided to you. Do not \
invent numbers, deals, guidance figures, or quotes. If the material does not support a \
claim, leave it out and say less.
- Use only URLs that appear in the material provided.
- Clean prose. No bullet points inside a brief or detail field. No em-dashes used as \
sentence connectors.
- Where the material supports it, connect the story to financing conditions, credit \
spreads, and capital structure, since that is her seat."""

MACRO_PROMPT = VOICE + """

MARKET DATA:
{market_data}

MACRO HEADLINES:
{headlines}

Return ONLY valid JSON, no markdown fences, no preamble:

{{
  "intro": "4-6 sentences framing the session. Reference actual figures from the data \
above. This is the paragraph she reads if she reads nothing else.",
  "macro": [
    {{
      "heading": "Short specific heading, not a generic category label",
      "brief": "3-4 sentences. What happened and the single reason it matters.",
      "detail": "Four substantial paragraphs, separated by newlines. Paragraph one: what \
happened in full, with the numbers. Paragraph two: the mechanism, meaning why this \
transmits to asset prices rather than just restating that it did. Paragraph three: the \
second-order effects, including what it means for credit conditions and financing \
markets where relevant. Paragraph four: what would confirm or break this read, and the \
specific thing to watch next. Be concrete throughout. This is the part she actually \
reads on the train, so it should reward the tap.",
      "sources": [{{"name": "Publication", "url": "https://..."}}]
    }}
  ],
  "events": ["4-6 short entries for non-earnings items on the calendar this week: data \
releases, central bank decisions, policy deadlines, notable scheduled meetings. Include \
the day of week where the headlines establish it. Only include items the headlines \
actually support."]
}}

Write exactly 3 macro entries."""

SECTOR_PROMPT = VOICE + """

You are writing the {sector_name} entry.

HOW THE SECTOR TRADED:
{sector_move}

BROADER MARKET CONTEXT:
{market_context}

{sector_name} HEADLINES:
{headlines}

Return ONLY valid JSON, no markdown fences, no preamble:

{{
  "heading": "{sector_name} — the specific angle in five words or fewer",
  "brief": "3-4 sentences. The dominant story in this sector right now and how it traded.",
  "detail": "Four substantial paragraphs, separated by newlines. Paragraph one: the \
dominant story in full, with specifics from the headlines. Paragraph two: which names or \
subsectors are driving the move and why the dispersion looks the way it does. Paragraph \
three: the balance sheet and financing angle, meaning how this environment affects the \
sector's cost of capital, refinancing needs, leverage tolerance, or M&A appetite. \
Paragraph four: the setup from here and the specific catalyst that would change it. Be \
concrete. Do not pad.",
  "sources": [{{"name": "Publication", "url": "https://..."}}]
}}

If the headlines are thin, write shorter and say so plainly rather than inventing \
material."""


ARTICLES_PROMPT = """You are curating the "Moving the Market" section of a morning \
equity research newsletter for a leveraged finance analyst.

This section is the big picture only. It answers one question: what is happening in the \
world right now that a markets professional needs to know about before the open. Wars, \
sanctions, elections, trade fights, supply disruptions, sovereign stress, central bank \
moves. Things with the scale to move whole markets, not one stock or one sector.

Below is every world and macro headline pulled this morning.

HEADLINES:
{pool}

Pick the 3 to 5 that genuinely matter, and return ONLY valid JSON, no markdown fences, \
no preamble:

{{
  "articles": [
    {{
      "id": 7,
      "why": "One sentence, under 25 words, on the market read. What it changes, not \
what it says."
    }}
  ]
}}

Selection rules:
- Use the "id" number exactly as given. Do not invent ids.
- Rank by market impact, most important first.
- Fewer is better. If only three stories truly matter this morning, return three. Never \
pad to reach five.
- Skip anything that only affects one company or one sector. That ground is already \
covered elsewhere in the newsletter.
- Skip opinion columns, listicles, personal finance advice, and promotional content.
- Drop duplicates. When several outlets carry the same story, keep the best one.
- Cover different ground. Do not return four angles on the same event.
- The "why" is the whole value. Name the transmission channel: rates, oil, the dollar, \
risk appetite, credit spreads, supply chains."""


def build_article_pool(world_news, macro_news, wire_news=None):
    """Flatten world, macro, and wire stories into one deduplicated, numbered pool.

    Sector headlines are deliberately excluded. Moving the Market is the big picture;
    sector news already has its own seven sections.
    """
    pool, seen_url, seen_title = [], set(), set()

    def norm(t):
        return "".join(c for c in t.lower() if c.isalnum() or c == " ")[:70].strip()

    def add(articles, tag):
        for a in articles:
            url, title = a.get("url", ""), a.get("title", "")
            if not url or not title:
                continue
            nt = norm(title)
            if url in seen_url or nt in seen_title:
                continue
            seen_url.add(url)
            seen_title.add(nt)
            pool.append({**a, "tag": tag, "id": len(pool)})

    for topic, arts in (world_news or {}).items():
        add(arts, topic)
    add(wire_news or [], "wire")
    for topic, arts in (macro_news or {}).items():
        add(arts, topic)
    return pool


def generate_top_articles(pool):
    """Ask Claude to pick and annotate the headlines actually worth reading."""
    if not pool:
        return []
    listing = "".join(
        f"[{a['id']}] {a['title']} ({a['source']}, {a['tag']})\n    {a['desc'][:200]}\n"
        for a in pool
    )
    try:
        result = call_claude(ARTICLES_PROMPT.format(pool=listing), max_tokens=2000)
    except Exception as e:
        print(f"  ! Article curation failed: {e}")
        return []

    by_id = {a["id"]: a for a in pool}
    out = []
    for pick in result.get("articles", []):
        art = by_id.get(pick.get("id"))
        if art:
            out.append({**art, "why": pick.get("why", "")})
    return out


def call_claude(prompt, max_tokens=4000):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    r.raise_for_status()
    text = "".join(
        b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text"
    ).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def market_summary_lines(market):
    lines = []
    for k, v in market.items():
        if k.startswith("sector_"):
            continue
        lines.append(f"{k}: {v['value']:,.2f} ({v.get('pct_change', 0):+.2f}%)")
    cpi = market.get("cpi_index", {})
    if "yoy" in cpi:
        lines.append(f"cpi_yoy: {cpi['yoy']:.2f}%")
    return "\n".join(lines)


def generate_macro(market, macro_news):
    blob = ""
    for topic, arts in macro_news.items():
        blob += f"\n## {topic.upper()}\n{headlines_blob(arts)}"
    try:
        return call_claude(
            MACRO_PROMPT.format(market_data=market_summary_lines(market), headlines=blob),
            max_tokens=6000,
        )
    except Exception as e:
        print(f"  ! Macro generation failed: {e}")
        return {
            "intro": "Editorial generation was unavailable this morning. Market data "
                     "below is current.",
            "macro": [],
            "events": [],
        }


def generate_sectors(market, sector_news):
    context = market_summary_lines(market)
    out = []
    for s in SECTORS:
        q = market.get(f"sector_{s['key']}")
        if q:
            move = (f"{s['etf']} ({s['name']} sector ETF): {q['value']:,.2f}, "
                    f"{q['pct_change']:+.2f}% on the session.")
        else:
            move = "Sector ETF quote unavailable this morning."
        try:
            entry = call_claude(
                SECTOR_PROMPT.format(
                    sector_name=s["name"],
                    sector_move=move,
                    market_context=context,
                    headlines=headlines_blob(sector_news.get(s["key"], [])),
                ),
                max_tokens=3000,
            )
            entry["sector_key"] = s["key"]
            entry["etf"] = s["etf"]
            entry["move"] = q["pct_change"] if q else None
            out.append(entry)
            print(f"    {s['name']} done")
        except Exception as e:
            print(f"  ! Sector {s['name']} failed: {e}")
    return out


# ----------------------------------------------------------------------------
# HTML rendering
# ----------------------------------------------------------------------------

def fmt_num(v, dec=2):
    return f"{v:,.{dec}f}"


def cell(label, data, note=None, source_url=None, value_suffix="", show_change=True):
    if not data:
        return (f'<td class="cell"><div class="cell-label">{html.escape(label)}</div>'
                f'<div class="cell-na">unavailable</div></td>')

    val = fmt_num(data["value"], data.get("decimals", 2)) + value_suffix
    parts = [f'<div class="cell-label">{html.escape(label)}']
    if note:
        parts.append(f'<span class="proxy" title="{html.escape(note)}">*</span>')
    parts.append("</div>")
    parts.append(f'<div class="cell-value">{val}')

    if show_change:
        chg = data.get("pct_change", 0.0)
        cls = "up" if chg > 0 else ("down" if chg < 0 else "flat")
        arrow = "&uarr;" if chg > 0 else ("&darr;" if chg < 0 else "&ndash;")
        parts.append(f' <span class="{cls}">{chg:+.2f}% {arrow}</span>')
    parts.append("</div>")

    if source_url:
        parts.append(
            f'<a class="cell-src" href="{html.escape(source_url)}" target="_blank" '
            f'rel="noopener">source</a>'
        )
    return f'<td class="cell">{"".join(parts)}</td>'


def fred_url(sid):
    return f"https://fred.stlouisfed.org/series/{sid}"


def finnhub_url(sym):
    return f"https://finnhub.io/quote/{sym}"


def build_snapshot(m):
    f = lambda k: m.get(k)
    fu = lambda k: fred_url(FRED_SERIES[k][0])
    pu = lambda k: finnhub_url(FINNHUB_PROXIES[k][0])
    pn = lambda k: f"Tracked via {FINNHUB_PROXIES[k][1]} as a proxy"

    cpi = f("cpi_index")
    cpi_cell = '<td class="cell"><div class="cell-label">U.S. Consumer Price Index</div>'
    if cpi and "yoy" in cpi:
        cpi_cell += (f'<div class="cell-value">{cpi["yoy"]:.2f}% '
                     f'<span class="muted">YoY</span></div>'
                     f'<a class="cell-src" href="{fred_url("CPIAUCSL")}" target="_blank" '
                     f'rel="noopener">source</a>')
    else:
        cpi_cell += '<div class="cell-na">unavailable</div>'
    cpi_cell += "</td>"

    unemp = f("unemployment")
    unemp_cell = '<td class="cell"><div class="cell-label">U.S. Unemployment Rate</div>'
    if unemp:
        d = unemp["abs_change"]
        tag = "no change" if abs(d) < 0.001 else f"{d:+.1f} pp"
        unemp_cell += (f'<div class="cell-value">{unemp["value"]:.1f}% '
                       f'<span class="muted">({tag})</span></div>'
                       f'<a class="cell-src" href="{fred_url("UNRATE")}" target="_blank" '
                       f'rel="noopener">source</a>')
    else:
        unemp_cell += '<div class="cell-na">unavailable</div>'
    unemp_cell += "</td>"

    rows = [
        [cell("S&P 500", f("sp500"), source_url=fu("sp500")),
         cell("NASDAQ Composite", f("nasdaq"), source_url=fu("nasdaq")),
         cell("Dow Jones", f("dow"), source_url=fu("dow"))],
        [cell("Russell 2000", f("russell"), pn("russell"), pu("russell")),
         cell("FTSE 100", f("ftse"), pn("ftse"), pu("ftse")),
         cell("Euro Stoxx 50", f("eurostoxx"), pn("eurostoxx"), pu("eurostoxx"))],
        [cell("Nikkei 225", f("nikkei"), source_url=fu("nikkei")),
         cell("Shanghai Composite", f("shanghai"), pn("shanghai"), pu("shanghai")),
         cell("MSCI Frontier Markets", f("frontier"), pn("frontier"), pu("frontier"))],
        [cell("WTI Crude Oil", f("wti"), source_url=fu("wti")),
         cell("Gold Spot Price /Oz", f("gold"), pn("gold"), pu("gold")),
         cell("U.S. High Yield Corporate Bond ETF", f("hyg"), pn("hyg"), pu("hyg"))],
        [cell("U.S. Dollar Index", f("dxy"), "Broad trade-weighted dollar index", fu("dxy")),
         cell("10-Year Treasury Yield", f("ust10"), source_url=fu("ust10"), value_suffix="%"),
         cell("CBOE Volatility Index", f("vix"), source_url=fu("vix"))],
        [cpi_cell, unemp_cell,
         cell("U.S. Secured Overnight Financing Rate", f("sofr"), source_url=fu("sofr"),
              value_suffix="%")],
        [cell("High Yield OAS Spread", f("hy_oas"), source_url=fu("hy_oas"), value_suffix="%"),
         cell("Investment Grade OAS Spread", f("ig_oas"), source_url=fu("ig_oas"),
              value_suffix="%"),
         cell("2-Year Treasury Yield", f("ust2"), source_url=fu("ust2"), value_suffix="%")],
    ]
    body = "".join(f"<tr>{''.join(r)}</tr>" for r in rows)
    return f'<table class="snapshot">{body}</table>'


def build_entry(item, idx, prefix, tag_html=""):
    sid = f"{prefix}-{idx}"
    srcs = ""
    if item.get("sources"):
        links = " · ".join(
            f'<a href="{html.escape(s.get("url", "#"))}" target="_blank" rel="noopener">'
            f'{html.escape(s.get("name", "source"))}</a>'
            for s in item["sources"] if s.get("url")
        )
        if links:
            srcs = f'<div class="srcs">Sources: {links}</div>'

    paras = "".join(
        f"<p>{html.escape(p.strip())}</p>"
        for p in item.get("detail", "").split("\n") if p.strip()
    )

    return f"""
    <article class="entry">
      <h3>{html.escape(item.get('heading', ''))}{tag_html}</h3>
      <p class="brief">{html.escape(item.get('brief', ''))}</p>
      <details id="{sid}">
        <summary>Read more</summary>
        <div class="detail">{paras}{srcs}</div>
      </details>
    </article>"""


def sector_tag(item):
    """Small move badge next to the sector heading."""
    mv = item.get("move")
    if mv is None:
        return ""
    cls = "up" if mv > 0 else ("down" if mv < 0 else "flat")
    return f' <span class="tag {cls}">{item.get("etf", "")} {mv:+.2f}%</span>'


def time_ago(iso):
    """Turn an ISO timestamp into a short relative label."""
    if not iso:
        return ""
    try:
        dt = datetime.strptime(iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        return ""
    hrs = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    if hrs < 1:
        return "just now"
    if hrs < 24:
        return f"{int(hrs)}h ago"
    return f"{int(hrs // 24)}d ago"


def build_articles(articles):
    if not articles:
        return ""

    rows = ""
    for a in articles:
        meta = " · ".join(x for x in (a.get("source", ""), time_ago(a.get("published", ""))) if x)
        why = a.get("why", "")
        rows += f"""
        <li class="art">
          <a class="art-head" href="{html.escape(a['url'])}" target="_blank" rel="noopener">{html.escape(a['title'])}</a>
          <div class="art-meta">{html.escape(meta)}</div>
          {f'<div class="art-why">{html.escape(why)}</div>' if why else ''}
        </li>"""

    return f"""
  <hr class="rule">
  <h2>Moving the Market</h2>
  <p class="section-note">World events with the reach to move markets, and the line on
  why each one matters.</p>
  <ol class="art-list">{rows}</ol>"""


def build_calendar(events, earnings):
    ev_html = ""
    if events:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in events)
        ev_html = f'<h3>Data and events</h3><ul class="cal-list">{items}</ul>'

    earn_html = ""
    if earnings:
        by_day = {}
        for e in earnings:
            by_day.setdefault(e["date"], []).append(e)

        blocks = []
        for date in sorted(by_day):
            try:
                label = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %-d")
            except Exception:
                label = date
            rows = ""
            for e in by_day[date]:
                when = {"bmo": "before open", "amc": "after close"}.get(e["hour"], "")
                est = f"est. ${e['eps_est']:.2f} EPS" if e.get("eps_est") is not None else ""
                meta = " · ".join(x for x in (when, est) if x)
                meta_html = f' <span class="meta">{html.escape(meta)}</span>' if meta else ""
                rows += (f'<li><span class="tick">{html.escape(e["symbol"])}</span> '
                         f'{html.escape(e["name"])}{meta_html}</li>')
            blocks.append(
                f'<div class="cal-day"><h4>{label}</h4>'
                f'<ul class="earn-list">{rows}</ul></div>'
            )

        earn_html = (
            "<h3>Earnings this week</h3>"
            + "".join(blocks)
            + '<div class="srcs">Schedule via <a href="https://finnhub.io/" '
              'target="_blank" rel="noopener">Finnhub</a>, filtered to large caps. '
              'Companies move dates, so confirm against the issuer\'s investor '
              'relations page before relying on it.</div>'
        )

    if not ev_html and not earn_html:
        return ""

    return f"""
  <hr class="rule">
  <h2>On the Calendar</h2>
  <section class="calendar">{ev_html}{earn_html}</section>"""


def build_html(market, macro_content, sectors, earnings, articles):
    date_long = TODAY.strftime("%A, %B %-d, %Y")
    date_short = TODAY.strftime("%B %-d, %Y")
    moving = build_articles(articles)

    macro = "".join(
        build_entry(x, i, "macro") for i, x in enumerate(macro_content.get("macro", []))
    )
    micro = "".join(
        build_entry(x, i, "sector", sector_tag(x)) for i, x in enumerate(sectors)
    )
    calendar = build_calendar(macro_content.get("events", []), earnings)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Market Brief — {date_short}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #000; --ink: #f2f2f2; --muted: #8a8a8a; --rule: #3a3a3a;
    --up: #4ade80; --down: #f87171;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 17px; line-height: 1.65; -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 780px; margin: 0 auto; padding: 40px 22px 90px; }}

  header.masthead {{ text-align: center; padding-bottom: 26px;
                     border-bottom: 1px solid var(--rule); }}
  .eyebrow {{ font-size: 11px; letter-spacing: .22em; text-transform: uppercase;
              color: var(--muted); font-weight: 600; }}
  h1 {{ font-family: 'Playfair Display', Georgia, serif; font-weight: 900;
        font-size: 40px; line-height: 1.12; margin: 14px 0 8px; }}
  .dateline {{ color: var(--muted); font-size: 14px; }}

  h2 {{ font-family: 'Playfair Display', Georgia, serif; font-weight: 700;
        font-size: 30px; text-align: center; margin: 52px 0 26px; }}
  h3 {{ font-size: 19px; font-weight: 700; margin: 36px 0 8px; }}
  h4 {{ font-size: 14px; font-weight: 700; margin: 20px 0 6px; letter-spacing: .04em; }}

  .intro p {{ margin: 0 0 16px; }}

  table.snapshot {{ width: 100%; border-collapse: collapse; table-layout: fixed;
                    font-size: 13px; line-height: 1.4; }}
  table.snapshot td.cell {{ border: 1px solid var(--ink); padding: 8px 9px;
                            vertical-align: top; width: 33.33%; }}
  .cell-label {{ font-weight: 700; font-size: 12.5px; }}
  .cell-value {{ font-size: 13px; margin-top: 2px; }}
  .cell-na {{ color: var(--muted); font-style: italic; font-size: 12px; }}
  .up {{ color: var(--up); }} .down {{ color: var(--down); }} .flat {{ color: var(--muted); }}
  .muted {{ color: var(--muted); }}
  .proxy {{ color: var(--muted); font-weight: 400; cursor: help; }}
  .cell-src {{ display: inline-block; margin-top: 3px; font-size: 10.5px;
               color: var(--muted); text-decoration: none;
               border-bottom: 1px dotted var(--muted); }}
  .cell-src:hover {{ color: var(--ink); }}
  .snapshot-note {{ text-align: center; color: var(--muted); font-size: 12.5px;
                    margin-top: 14px; }}

  .entry {{ padding-bottom: 6px; }}
  .brief {{ margin: 0 0 10px; }}
  .tag {{ font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
          border: 1px solid currentColor; border-radius: 3px; padding: 1px 6px;
          vertical-align: middle; white-space: nowrap; }}
  details {{ border-top: 1px solid var(--rule); padding-top: 8px; }}
  summary {{ cursor: pointer; color: var(--muted); font-size: 13px; font-weight: 600;
             letter-spacing: .04em; list-style: none; }}
  summary::-webkit-details-marker {{ display: none; }}
  summary::after {{ content: " ↓"; }}
  details[open] summary::after {{ content: " ↑"; }}
  summary:hover {{ color: var(--ink); }}
  .detail {{ padding-top: 10px; font-size: 16px; color: #d8d8d8; }}
  .detail p {{ margin: 0 0 14px; }}
  .srcs {{ font-size: 12.5px; color: var(--muted); }}
  .srcs a {{ color: var(--muted); }}

  .section-note {{ text-align: center; color: var(--muted); font-size: 13.5px;
                   margin: -14px 0 24px; }}
  ol.art-list {{ list-style: none; counter-reset: art; padding: 0; margin: 0; }}
  li.art {{ counter-increment: art; position: relative; padding: 14px 0 14px 34px;
            border-bottom: 1px solid rgba(255,255,255,.08); }}
  li.art::before {{ content: counter(art, decimal-leading-zero); position: absolute;
                    left: 0; top: 16px; font-size: 12px; font-weight: 700;
                    color: var(--muted); font-variant-numeric: tabular-nums; }}
  .art-head {{ display: block; font-size: 16.5px; font-weight: 600; line-height: 1.4;
               color: var(--ink); text-decoration: none; }}
  .art-head:hover {{ text-decoration: underline; }}
  .art-meta {{ font-size: 12.5px; color: var(--muted); margin-top: 3px; }}
  .art-why {{ font-size: 14.5px; color: #c4c4c4; margin-top: 6px;
              border-left: 2px solid var(--rule); padding-left: 10px; }}

  .cal-list {{ padding-left: 20px; }}
  .cal-list li {{ margin-bottom: 8px; }}
  .cal-day {{ margin-bottom: 4px; }}
  ul.earn-list {{ list-style: none; padding: 0; margin: 0 0 6px; }}
  ul.earn-list li {{ font-size: 15px; padding: 3px 0;
                     border-bottom: 1px solid rgba(255,255,255,.06); }}
  .tick {{ display: inline-block; min-width: 62px; font-weight: 700;
           font-variant-numeric: tabular-nums; }}
  .meta {{ color: var(--muted); font-size: 13px; }}

  hr.rule {{ border: 0; border-top: 1px solid var(--rule); margin: 52px 0; }}
  footer {{ color: var(--muted); font-size: 12.5px; text-align: center; }}
  footer a {{ color: var(--muted); }}

  @media (max-width: 620px) {{
    body {{ font-size: 16px; }}
    h1 {{ font-size: 30px; }} h2 {{ font-size: 24px; }}
    table.snapshot, table.snapshot tbody, table.snapshot tr, table.snapshot td.cell {{
      display: block; width: 100%; }}
    table.snapshot td.cell {{ border-top: none; }}
    table.snapshot tr:first-child td.cell:first-child {{ border-top: 1px solid var(--ink); }}
    .tick {{ min-width: 54px; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; transition: none !important; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <header class="masthead">
    <div class="eyebrow">Daily Market Brief</div>
    <h1>Morning Edition</h1>
    <div class="dateline">{date_long}</div>
  </header>

  <h2>Newsletter Summary</h2>
  <div class="intro"><p>{html.escape(macro_content.get('intro', ''))}</p></div>

  <hr class="rule">

  <h2>Markets Snapshot</h2>
  {build_snapshot(market)}
  <div class="snapshot-note">
    Sources: <a href="https://fred.stlouisfed.org/">FRED (Federal Reserve Bank of
    St.&nbsp;Louis)</a> and <a href="https://finnhub.io/">Finnhub</a>. Cells marked *
    use a listed ETF as a proxy for the underlying index; hover the asterisk for the
    instrument used.
  </div>
  {moving}

  <hr class="rule">

  <h2>Macro Update</h2>
  {macro or '<p class="muted">No macro entries this morning.</p>'}

  <hr class="rule">

  <h2>Sector Update</h2>
  {micro or '<p class="muted">No sector entries this morning.</p>'}
  {calendar}

  <hr class="rule">

  <footer>
    Built {TODAY.strftime('%Y-%m-%d %H:%M')} ET. Summaries are generated from published
    headlines and may contain errors. Verify before acting on anything here.
  </footer>

</div>
</body>
</html>"""


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    print("Fetching FRED...")
    market = fetch_fred_all()
    print(f"  {len(market)} series")

    print("Fetching Finnhub quotes and sector ETFs...")
    market.update(fetch_finnhub_all())

    print("Fetching earnings calendar...")
    earnings = fetch_earnings_calendar()
    print(f"  {len(earnings)} large-cap reports in the next 8 days")

    print("Fetching market wire (Finnhub)...")
    wire = fetch_finnhub_news()
    print(f"  {len(wire)} wire stories")

    print("Fetching macro headlines...")
    macro_news = {k: news_for(q) for k, q in MACRO_TOPICS.items()}
    macro_news["wire"] = wire

    print("Fetching world headlines...")
    world_news = {k: news_for(q, limit=8) for k, q in WORLD_TOPICS.items()}

    print("Fetching sector headlines...")
    sector_news = {s["key"]: news_for(s["query"]) for s in SECTORS}

    print("Generating macro section...")
    macro_content = generate_macro(market, macro_news)

    print("Generating sector sections...")
    sectors = generate_sectors(market, sector_news)

    print("Curating Moving the Market...")
    pool = build_article_pool(
        world_news, {k: v for k, v in macro_news.items() if k != "wire"}, wire
    )
    print(f"  {len(pool)} unique world and macro articles in pool")
    articles = generate_top_articles(pool)
    print(f"  {len(articles)} selected")

    print("Writing index.html...")
    page = build_html(market, macro_content, sectors, earnings, articles)
    with open("index.html", "w", encoding="utf-8") as fh:
        fh.write(page)

    os.makedirs("archive", exist_ok=True)
    with open(f"archive/{TODAY.strftime('%Y-%m-%d')}.html", "w", encoding="utf-8") as fh:
        fh.write(page)

    print("Done.")


if __name__ == "__main__":
    main()
