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
            timeout=12,
        )
        r.raise_for_status()
        return parse_rss(r.text, query[:30], limit)
    except Exception as e:
        print(f"  ! Google News failed ({query[:30]}...): {e}")
        return []


def news_batch(topics, limit=10):
    """Fetch several RSS queries at once. topics is {key: query}."""
    from concurrent.futures import ThreadPoolExecutor

    keys = list(topics)
    with ThreadPoolExecutor(max_workers=max(1, len(keys))) as pool:
        results = list(pool.map(lambda k: news_for(topics[k], limit), keys))
    return dict(zip(keys, results))


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
      "detail": [
        "Paragraph one: what happened in full, with the numbers.",
        "Paragraph two: the mechanism, meaning why this transmits to asset prices \
rather than just restating that it did.",
        "Paragraph three: the second-order effects, including what it means for credit \
conditions and financing markets where relevant.",
        "Paragraph four: what would confirm or break this read, and the specific thing \
to watch next."
      ],
      "sources": [{{"name": "Publication", "url": "https://..."}}]
    }}
  ],
  "events": ["4-6 short entries for non-earnings items on the calendar this week: data \
releases, central bank decisions, policy deadlines, notable scheduled meetings. Include \
the day of week where the headlines establish it. Only include items the headlines \
actually support."]
}}

"detail" is an array of exactly four strings, one per paragraph. Each should be \
substantial and concrete. Never put a line break inside any string.

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
  "heading": "The specific angle, six words or fewer. Do NOT include the sector name, \
it is displayed separately above this. Write 'Sanctions reprice the crude curve', not \
'Energy — sanctions reprice the crude curve'.",
  "brief": "3-4 sentences. The dominant story in this sector right now and how it traded.",
  "detail": [
    "Paragraph one: the dominant story in full, with specifics from the headlines.",
    "Paragraph two: which names or subsectors are driving the move and why the \
dispersion looks the way it does.",
    "Paragraph three: the balance sheet and financing angle, meaning how this \
environment affects the sector's cost of capital, refinancing needs, leverage \
tolerance, or M&A appetite.",
    "Paragraph four: the setup from here and the specific catalyst that would change it."
  ],
  "sources": [{{"name": "Publication", "url": "https://..."}}]
}}

"detail" is an array of exactly four strings, one per paragraph. Each should be \
substantial and concrete. Never put a line break inside any string.

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
        result = call_claude(ARTICLES_PROMPT.format(pool=listing), max_tokens=3000,
                             label="article curation")
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


def extract_json(text):
    """Pull a JSON object out of a model response and parse it leniently.

    Handles markdown fences, stray preamble, and literal control characters inside
    strings (strict=False), which strict JSON rejects but models emit anyway.
    """
    text = text.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]

    # Fall back to the outermost braces, which survives any leading or trailing prose
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]

    return json.loads(text.strip(), strict=False)


def call_claude(prompt, max_tokens=8000, label="", retry=True):
    """Call the API and parse JSON out of the response, retrying once on failure."""
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
        timeout=240,
    )
    r.raise_for_status()
    payload = r.json()

    text = "".join(
        b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"
    )

    # A response cut off at the token ceiling is never valid JSON. Say so plainly
    # rather than surfacing a confusing parse error.
    if payload.get("stop_reason") == "max_tokens":
        print(f"  ! {label or 'response'} hit the token ceiling ({max_tokens})")
        if retry:
            print(f"    retrying with a higher ceiling")
            return call_claude(prompt, max_tokens=max_tokens * 2, label=label, retry=False)

    try:
        return extract_json(text)
    except json.JSONDecodeError as e:
        if not retry:
            raise
        print(f"  ! {label or 'response'} returned malformed JSON ({e}); retrying")
        repair = (
            prompt
            + "\n\nIMPORTANT: your previous attempt was not valid JSON. Return a single "
              "JSON object and nothing else. No markdown fences. No text before or after. "
              "Never place a raw line break inside a string value."
        )
        return call_claude(repair, max_tokens=max_tokens, label=label, retry=False)


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
            max_tokens=16000,
            label="macro section",
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
    """Write all sector entries. Runs in parallel since none depends on another."""
    from concurrent.futures import ThreadPoolExecutor

    context = market_summary_lines(market)

    def one(s):
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
                max_tokens=8000,
                label=f"{s['name']} sector",
            )
            entry["sector_key"] = s["key"]
            entry["sector_name"] = s["name"]
            entry["etf"] = s["etf"]
            entry["move"] = q["pct_change"] if q else None
            print(f"    {s['name']} done")
            return entry
        except Exception as e:
            print(f"  ! Sector {s['name']} failed: {e}")
            return None

    with ThreadPoolExecutor(max_workers=len(SECTORS)) as pool:
        results = list(pool.map(one, SECTORS))

    return [r for r in results if r]


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


def scan_archive(include_today=True):
    """Read the archive folder and return editions newest-first, grouped by month.

    Returns a list of {month_label, entries} where each entry is
    {date, label, filename, is_today}.
    """
    dates = set()
    if os.path.isdir("archive"):
        for fn in os.listdir("archive"):
            if not fn.endswith(".html"):
                continue
            stem = fn[:-5]
            try:
                datetime.strptime(stem, "%Y-%m-%d")
                dates.add(stem)
            except ValueError:
                continue

    today = TODAY.strftime("%Y-%m-%d")
    if include_today:
        dates.add(today)

    groups, current = [], None
    for d in sorted(dates, reverse=True):
        dt = datetime.strptime(d, "%Y-%m-%d")
        month_label = dt.strftime("%B %Y")
        if current is None or current["month_label"] != month_label:
            current = {"month_label": month_label, "entries": []}
            groups.append(current)
        current["entries"].append({
            "date": d,
            "label": dt.strftime("%A %-m/%-d"),
            "filename": f"{d}.html",
            "is_today": d == today,
        })
    return groups


def archive_list_html(groups, href_prefix, current_date=None):
    """Render the grouped edition list. Shared by the drawer and the archive page."""
    if not groups:
        return '<p class="arc-empty">No past editions yet.</p>'

    out = ""
    for g in groups:
        out += f'<div class="arc-month">{html.escape(g["month_label"])}</div><ul class="arc-list">'
        for e in g["entries"]:
            if e["date"] == current_date:
                out += f'<li class="arc-item current">{html.escape(e["label"])}<span class="arc-now">reading</span></li>'
            else:
                href = f'{href_prefix}{e["filename"]}'
                out += (f'<li class="arc-item"><a href="{html.escape(href)}">'
                        f'{html.escape(e["label"])}</a></li>')
        out += "</ul>"
    return out


def build_drawer(groups, href_prefix, current_date, home_href):
    """Desktop slide-out drawer plus the mobile link to the standalone archive page."""
    listing = archive_list_html(groups, href_prefix, current_date)
    count = sum(len(g["entries"]) for g in groups)

    return f"""
  <button class="arc-toggle desktop-only" id="arcToggle" aria-expanded="false"
          aria-controls="arcDrawer">Previous Editions</button>
  <a class="arc-toggle mobile-only" href="{html.escape(home_href)}archive.html">Previous Editions</a>

  <div class="arc-scrim" id="arcScrim" hidden></div>
  <aside class="arc-drawer" id="arcDrawer" aria-label="Previous editions" hidden>
    <div class="arc-head">
      <span>Previous Editions</span>
      <button class="arc-close" id="arcClose" aria-label="Close">&times;</button>
    </div>
    <div class="arc-body">
      <div class="arc-count">{count} edition{'s' if count != 1 else ''}</div>
      {listing}
    </div>
  </aside>"""


DRAWER_JS = """
<script>
(function () {
  var t = document.getElementById('arcToggle');
  var d = document.getElementById('arcDrawer');
  var s = document.getElementById('arcScrim');
  var c = document.getElementById('arcClose');
  if (!t || !d || !s) return;

  function open() {
    d.hidden = false; s.hidden = false;
    requestAnimationFrame(function () {
      d.classList.add('open'); s.classList.add('open');
    });
    t.setAttribute('aria-expanded', 'true');
  }
  function close() {
    d.classList.remove('open'); s.classList.remove('open');
    t.setAttribute('aria-expanded', 'false');
    setTimeout(function () { d.hidden = true; s.hidden = true; }, 220);
    t.focus();
  }
  function toggle() {
    if (d.classList.contains('open')) { close(); } else { open(); }
  }

  t.addEventListener('click', toggle);
  s.addEventListener('click', close);
  if (c) c.addEventListener('click', close);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && d.classList.contains('open')) close();
  });
})();
</script>"""


def build_entry(item, idx, prefix, tag_html="", label=""):
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

    detail = item.get("detail", "")
    if isinstance(detail, str):
        # Fallback for the older newline-separated shape
        chunks = [p for p in detail.split("\n") if p.strip()]
    elif isinstance(detail, list):
        chunks = [str(p) for p in detail if str(p).strip()]
    else:
        chunks = []
    paras = "".join(f"<p>{html.escape(p.strip())}</p>" for p in chunks)

    label_html = (
        f'<div class="entry-label">{html.escape(label)}{tag_html}</div>' if label else ""
    )
    heading_tag = "" if label else tag_html

    return f"""
    <article class="entry">
      {label_html}
      <h3>{html.escape(item.get('heading', ''))}{heading_tag}</h3>
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


def build_archive_page(groups):
    """Standalone list of every past edition. This is what mobile links to."""
    listing = archive_list_html(groups, "archive/", None)
    count = sum(len(g["entries"]) for g in groups)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Previous Editions — Daily Market Brief</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{ --bg:#000; --ink:#f2f2f2; --muted:#8a8a8a; --rule:#3a3a3a; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif;
    font-size:17px; line-height:1.65; -webkit-font-smoothing:antialiased;
  }}
  .wrap {{ max-width:640px; margin:0 auto; padding:40px 22px 80px; }}
  .eyebrow {{
    font-size:11px; letter-spacing:.22em; text-transform:uppercase;
    color:var(--muted); font-weight:600; text-align:center;
  }}
  h1 {{
    font-family:'Playfair Display', Georgia, serif; font-weight:900;
    font-size:34px; text-align:center; margin:12px 0 6px;
  }}
  .count {{ text-align:center; color:var(--muted); font-size:13px; margin-bottom:8px; }}
  .back {{ display:block; text-align:center; color:var(--muted); font-size:13.5px;
           margin-bottom:26px; }}
  .back:hover {{ color:var(--ink); }}
  hr.rule {{ border:0; border-top:1px solid var(--rule); margin:0 0 8px; }}
  .arc-month {{
    font-size:11px; letter-spacing:.16em; text-transform:uppercase;
    color:var(--muted); font-weight:700;
    border-bottom:1px solid var(--rule); padding-bottom:6px; margin:30px 0 8px;
  }}
  ul.arc-list {{ list-style:none; padding:0; margin:0; }}
  .arc-item {{ font-size:16px; padding:9px 0;
               border-bottom:1px solid rgba(255,255,255,.06); }}
  .arc-item a {{ color:var(--ink); text-decoration:none; display:block; }}
  .arc-item a:hover {{ text-decoration:underline; }}
  .arc-item.current {{ color:var(--muted); display:flex;
                       justify-content:space-between; align-items:baseline; }}
  .arc-now {{ font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; }}
  .arc-empty {{ color:var(--muted); }}
  @media (prefers-reduced-motion: reduce) {{
    * {{ animation:none !important; transition:none !important; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">Daily Market Brief</div>
  <h1>Previous Editions</h1>
  <div class="count">{count} edition{'s' if count != 1 else ''} archived</div>
  <a class="back" href="index.html">&larr; Back to the latest edition</a>
  <hr class="rule">
  {listing}
</div>
</body>
</html>"""


def build_email_html(market, macro_content, sectors, earnings, articles, site_url):
    """A table-based, inline-styled version of the brief for email clients.

    Email clients strip <style> blocks and ignore most modern CSS, so this uses
    tables and inline attributes throughout. Detail paragraphs are omitted; the
    email carries the scannable version and links out for the full read.
    """
    BG, INK, MUTED, RULE = "#000000", "#f2f2f2", "#8a8a8a", "#3a3a3a"
    UP, DOWN = "#4ade80", "#f87171"

    def esc(t):
        return html.escape(str(t))

    def quote_cell(label, data, suffix="", yoy=False):
        if not data:
            return (f'<td width="33%" valign="top" bgcolor="{BG}" '
                    f'style="border:1px solid {INK};padding:8px;color:{MUTED};'
                    f'font-size:12px;font-family:Arial,sans-serif;">{esc(label)}<br>'
                    f'<em>unavailable</em></td>')
        if yoy and "yoy" in data:
            val, chg_html = f'{data["yoy"]:.2f}% YoY', ""
        else:
            val = f'{data["value"]:,.{data.get("decimals", 2)}f}{suffix}'
            chg = data.get("pct_change", 0.0)
            color = UP if chg > 0 else (DOWN if chg < 0 else MUTED)
            arrow = "&uarr;" if chg > 0 else ("&darr;" if chg < 0 else "&ndash;")
            chg_html = f' <span style="color:{color};">{chg:+.2f}% {arrow}</span>'
        return (f'<td width="33%" valign="top" bgcolor="{BG}" '
                f'style="border:1px solid {INK};padding:8px;color:{INK};font-size:12px;'
                f'font-family:Arial,sans-serif;line-height:1.4;">'
                f'<strong>{esc(label)}</strong><br>{val}{chg_html}</td>')

    m = market
    snapshot_rows = [
        [quote_cell("S&P 500", m.get("sp500")), quote_cell("NASDAQ", m.get("nasdaq")),
         quote_cell("Dow Jones", m.get("dow"))],
        [quote_cell("Russell 2000*", m.get("russell")), quote_cell("FTSE 100*", m.get("ftse")),
         quote_cell("Euro Stoxx 50*", m.get("eurostoxx"))],
        [quote_cell("Nikkei 225", m.get("nikkei")), quote_cell("Shanghai*", m.get("shanghai")),
         quote_cell("MSCI Frontier*", m.get("frontier"))],
        [quote_cell("WTI Crude", m.get("wti")), quote_cell("Gold /oz*", m.get("gold")),
         quote_cell("U.S. HY Bond ETF*", m.get("hyg"))],
        [quote_cell("U.S. Dollar Index", m.get("dxy")),
         quote_cell("10-Year Treasury", m.get("ust10"), "%"),
         quote_cell("VIX", m.get("vix"))],
        [quote_cell("U.S. CPI", m.get("cpi_index"), yoy=True),
         quote_cell("Unemployment", m.get("unemployment"), "%"),
         quote_cell("SOFR", m.get("sofr"), "%")],
        [quote_cell("High Yield OAS", m.get("hy_oas"), "%"),
         quote_cell("Investment Grade OAS", m.get("ig_oas"), "%"),
         quote_cell("2-Year Treasury", m.get("ust2"), "%")],
    ]
    snapshot = "".join(f"<tr>{''.join(r)}</tr>" for r in snapshot_rows)

    def h2(text):
        return (f'<tr><td style="padding:34px 0 14px;color:{INK};font-size:22px;'
                f'font-weight:bold;font-family:Georgia,serif;text-align:center;">'
                f'{esc(text)}</td></tr>')

    def para(text, size=15, color=INK, pad="0 0 12px"):
        return (f'<tr><td style="padding:{pad};color:{color};font-size:{size}px;'
                f'line-height:1.6;font-family:Arial,sans-serif;">{text}</td></tr>')

    body = ""

    body += h2("Newsletter Summary")
    body += para(esc(macro_content.get("intro", "")))

    body += h2("Markets Snapshot")
    body += (f'<tr><td style="padding-bottom:6px;"><table width="100%" cellpadding="0" '
             f'cellspacing="0" border="0" style="border-collapse:collapse;">'
             f'{snapshot}</table></td></tr>')
    body += para("* tracked via a listed ETF as a proxy. Sources: FRED and Finnhub.",
                 size=11, color=MUTED, pad="6px 0 0")

    if articles:
        body += h2("Moving the Market")
        for a in articles:
            meta = " &middot; ".join(
                x for x in (esc(a.get("source", "")), time_ago(a.get("published", ""))) if x
            )
            body += para(
                f'<a href="{esc(a["url"])}" style="color:{INK};text-decoration:none;'
                f'font-weight:bold;">{esc(a["title"])}</a><br>'
                f'<span style="color:{MUTED};font-size:12px;">{meta}</span><br>'
                f'<span style="color:#c4c4c4;font-size:14px;">{esc(a.get("why", ""))}</span>',
                pad="0 0 16px",
            )

    def entry_block(items, tag_fn=None, show_label=False):
        out = ""
        for x in items:
            tag = tag_fn(x) if tag_fn else ""
            name = x.get("sector_name", "") if show_label else ""
            label = (
                f'<span style="color:{MUTED};font-size:11px;letter-spacing:2px;">'
                f'{esc(name.upper())}</span>{tag}<br>' if name else ""
            )
            out += para(
                f'{label}'
                f'<strong style="font-size:17px;">{esc(x.get("heading", ""))}</strong>'
                f'{"" if name else tag}<br>'
                f'{esc(x.get("brief", ""))}',
                pad="0 0 18px",
            )
        return out

    def email_tag(x):
        mv = x.get("move")
        if mv is None:
            return ""
        color = UP if mv > 0 else (DOWN if mv < 0 else MUTED)
        return f' <span style="color:{color};font-size:13px;">{x.get("etf","")} {mv:+.2f}%</span>'

    if macro_content.get("macro"):
        body += h2("Macro Update")
        body += entry_block(macro_content["macro"])

    if sectors:
        body += h2("Sector Update")
        body += entry_block(sectors, email_tag, show_label=True)

    if macro_content.get("events") or earnings:
        body += h2("On the Calendar")
        if macro_content.get("events"):
            ev = "<br>".join(f"&bull; {esc(e)}" for e in macro_content["events"])
            body += para(ev, pad="0 0 14px")
        if earnings:
            by_day = {}
            for e in earnings:
                by_day.setdefault(e["date"], []).append(e)
            for date in sorted(by_day):
                try:
                    label = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %-d")
                except Exception:
                    label = date
                names = ", ".join(
                    f'{esc(e["symbol"])} ({esc(e["name"])})' for e in by_day[date]
                )
                body += para(
                    f'<strong style="font-size:13px;">{label}</strong><br>'
                    f'<span style="font-size:14px;">{names}</span>',
                    pad="0 0 10px",
                )

    link_btn = (
        f'<tr><td align="center" style="padding:18px 0 8px;">'
        f'<a href="{esc(site_url)}" style="display:inline-block;padding:11px 22px;'
        f'border:1px solid {INK};color:{INK};text-decoration:none;font-size:14px;'
        f'font-family:Arial,sans-serif;">Read the full edition &rarr;</a></td></tr>'
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:{BG};">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{BG}">
<tr><td align="center" style="padding:26px 14px 50px;">
<table width="100%" cellpadding="0" cellspacing="0" border="0"
       style="max-width:620px;width:100%;">

  <tr><td align="center" style="padding-bottom:8px;color:{MUTED};font-size:10px;
      letter-spacing:2px;font-family:Arial,sans-serif;">DAILY MARKET BRIEF</td></tr>
  <tr><td align="center" style="color:{INK};font-size:30px;font-weight:bold;
      font-family:Georgia,serif;padding-bottom:6px;">Morning Edition</td></tr>
  <tr><td align="center" style="color:{MUTED};font-size:13px;
      font-family:Arial,sans-serif;padding-bottom:10px;">
      {TODAY.strftime('%A, %B %-d, %Y')}</td></tr>
  {link_btn}
  <tr><td style="border-top:1px solid {RULE};padding-top:4px;"></td></tr>

  {body}

  {link_btn}
  <tr><td align="center" style="padding-top:24px;color:{MUTED};font-size:11px;
      line-height:1.5;font-family:Arial,sans-serif;">
      Summaries are generated from published headlines and may contain errors.
      Verify before acting on anything here.</td></tr>

</table>
</td></tr></table>
</body></html>"""


def send_email(subject, html_body):
    """Send the brief via Gmail SMTP. Skips silently if not configured."""
    user = os.environ.get("GMAIL_USER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipients = [
        a.strip() for a in os.environ.get("EMAIL_TO", "").split(",") if a.strip()
    ]

    if not (user and password and recipients):
        print("  email not configured, skipping")
        return False

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Market Brief <{user}>"
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=45) as server:
            server.login(user, password)
            server.sendmail(user, recipients, msg.as_string())
        print(f"  sent to {len(recipients)} recipient(s)")
        return True
    except Exception as e:
        print(f"  ! Email failed: {e}")
        return False


def build_html(market, macro_content, sectors, earnings, articles,
               archive_groups=None, in_archive=False, edition_date=None):
    """Render the full page.

    in_archive shifts relative links, since archived copies live one folder down.
    """
    date_long = TODAY.strftime("%A, %B %-d, %Y")
    date_short = TODAY.strftime("%B %-d, %Y")
    moving = build_articles(articles)

    # Archived copies sit in archive/, so sibling editions are alongside them and the
    # site root is one level up.
    href_prefix = "" if in_archive else "archive/"
    home_href = "../" if in_archive else ""

    drawer = build_drawer(
        archive_groups or [], href_prefix,
        edition_date or TODAY.strftime("%Y-%m-%d"), home_href,
    )

    macro = "".join(
        build_entry(x, i, "macro") for i, x in enumerate(macro_content.get("macro", []))
    )
    micro = "".join(
        build_entry(x, i, "sector", sector_tag(x), x.get("sector_name", ""))
        for i, x in enumerate(sectors)
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
  .entry-label {{
    font-size: 11px; letter-spacing: .18em; text-transform: uppercase;
    color: var(--muted); font-weight: 700; margin: 36px 0 2px;
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }}
  .entry-label + h3 {{ margin-top: 0; }}
  .brief {{ margin: 0 0 10px; }}

  /* ---- Archive drawer ---- */
  .arc-toggle {{
    position: fixed; left: 0; top: 96px; z-index: 40;
    background: var(--bg); color: var(--muted);
    border: 1px solid var(--rule); border-left: none;
    border-radius: 0 4px 4px 0; padding: 10px 12px;
    font-family: inherit; font-size: 11px; font-weight: 600;
    letter-spacing: .12em; text-transform: uppercase;
    writing-mode: vertical-rl; cursor: pointer; text-decoration: none;
  }}
  .arc-toggle:hover {{ color: var(--ink); border-color: var(--ink); }}
  .arc-scrim {{
    position: fixed; inset: 0; background: rgba(0,0,0,.6); z-index: 50;
    opacity: 0; transition: opacity .2s ease;
  }}
  .arc-scrim.open {{ opacity: 1; }}
  .arc-drawer {{
    position: fixed; left: 0; top: 0; bottom: 0; width: 300px; max-width: 84vw;
    background: #0a0a0a; border-right: 1px solid var(--rule); z-index: 60;
    transform: translateX(-100%); transition: transform .22s ease;
    display: flex; flex-direction: column;
  }}
  .arc-drawer.open {{ transform: translateX(0); }}
  .arc-head {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 18px 14px; border-bottom: 1px solid var(--rule);
    font-size: 12px; letter-spacing: .16em; text-transform: uppercase;
    color: var(--ink); font-weight: 700;
  }}
  .arc-close {{
    background: none; border: none; color: var(--muted);
    font-size: 24px; line-height: 1; cursor: pointer; padding: 0 2px;
  }}
  .arc-close:hover {{ color: var(--ink); }}
  .arc-body {{ overflow-y: auto; padding: 14px 18px 30px; }}
  .arc-count {{ font-size: 11.5px; color: var(--muted); margin-bottom: 12px; }}
  .arc-month {{
    font-size: 11px; letter-spacing: .16em; text-transform: uppercase;
    color: var(--muted); font-weight: 700;
    border-bottom: 1px solid var(--rule); padding-bottom: 5px; margin: 18px 0 6px;
  }}
  ul.arc-list {{ list-style: none; padding: 0; margin: 0; }}
  .arc-item {{ font-size: 14.5px; padding: 5px 0; }}
  .arc-item a {{ color: var(--ink); text-decoration: none; }}
  .arc-item a:hover {{ text-decoration: underline; }}
  .arc-item.current {{
    color: var(--muted); display: flex; justify-content: space-between;
    align-items: baseline; gap: 8px;
  }}
  .arc-now {{ font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; }}
  .arc-empty {{ color: var(--muted); font-size: 14px; }}
  .desktop-only {{ display: block; }}
  .mobile-only {{ display: none; }}
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
    .desktop-only {{ display: none; }}
    .mobile-only {{ display: block; }}
    .arc-toggle {{ top: auto; bottom: 18px; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; transition: none !important; }}
  }}
</style>
</head>
<body>
{drawer}
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
    {f'<p><a href="{home_href}index.html">&larr; Back to the latest edition</a></p>' if in_archive else ''}
    Built {TODAY.strftime('%Y-%m-%d %H:%M')} ET. Summaries are generated from published
    headlines and may contain errors. Verify before acting on anything here.
  </footer>

</div>
{DRAWER_JS}
</body>
</html>"""


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    import time
    t_start = time.time()
    marks = []

    def stage(label):
        now = time.time()
        if marks:
            print(f"    [{now - marks[-1][1]:.1f}s]")
        marks.append((label, now))
        print(label)

    stage("Fetching FRED...")
    market = fetch_fred_all()
    print(f"  {len(market)} series")

    stage("Fetching Finnhub quotes and sector ETFs...")
    market.update(fetch_finnhub_all())

    stage("Fetching earnings calendar...")
    earnings = fetch_earnings_calendar()
    print(f"  {len(earnings)} large-cap reports in the next 8 days")

    stage("Fetching market wire (Finnhub)...")
    wire = fetch_finnhub_news()
    print(f"  {len(wire)} wire stories")

    stage("Fetching macro headlines...")
    macro_news = news_batch(MACRO_TOPICS)
    macro_news["wire"] = wire

    stage("Fetching world headlines...")
    world_news = news_batch(WORLD_TOPICS, limit=8)

    stage("Fetching sector headlines...")
    sector_news = news_batch({s["key"]: s["query"] for s in SECTORS})

    stage("Generating macro section...")
    macro_content = generate_macro(market, macro_news)
    print(f"  {len(macro_content.get('macro', []))} macro entries written")

    stage("Generating sector sections...")
    sectors = generate_sectors(market, sector_news)
    print(f"  {len(sectors)} of {len(SECTORS)} sectors written")

    stage("Curating Moving the Market...")
    pool = build_article_pool(
        world_news, {k: v for k, v in macro_news.items() if k != "wire"}, wire
    )
    print(f"  {len(pool)} unique world and macro articles in pool")
    articles = generate_top_articles(pool)
    print(f"  {len(articles)} selected")

    stage("Writing pages...")
    os.makedirs("archive", exist_ok=True)
    groups = scan_archive(include_today=True)
    total = sum(len(g["entries"]) for g in groups)
    print(f"  {total} editions in the archive")

    today_stamp = TODAY.strftime("%Y-%m-%d")

    # Root copy: sibling editions live under archive/
    with open("index.html", "w", encoding="utf-8") as fh:
        fh.write(build_html(
            market, macro_content, sectors, earnings, articles,
            archive_groups=groups, in_archive=False, edition_date=today_stamp,
        ))

    # Archived copy: siblings are alongside it, so links drop the folder prefix
    with open(f"archive/{today_stamp}.html", "w", encoding="utf-8") as fh:
        fh.write(build_html(
            market, macro_content, sectors, earnings, articles,
            archive_groups=groups, in_archive=True, edition_date=today_stamp,
        ))

    with open("archive.html", "w", encoding="utf-8") as fh:
        fh.write(build_archive_page(groups))

    stage("Sending email...")
    site_url = os.environ.get("SITE_URL", "").strip()
    email_html = build_email_html(
        market, macro_content, sectors, earnings, articles, site_url
    )
    send_email(f"Market Brief — {TODAY.strftime('%B %-d, %Y')}", email_html)

    print(f"    [{time.time() - marks[-1][1]:.1f}s]")
    print(f"Done in {time.time() - t_start:.1f}s total.")


if __name__ == "__main__":
    main()
