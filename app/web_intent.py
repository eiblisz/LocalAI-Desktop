import re


def looks_like_web_request(text):
    normalized = " ".join(str(text or "").lower().split())
    markers = [
        "keress rá",
        "keress ra",
        "keresd meg",
        "keress nekem",
        "nézd meg online",
        "nezd meg online",
        "nézz utána",
        "nezz utana",
        "interneten",
        "az interneten",
        "weben",
        "web-en",
        "online",
        "legfrissebb",
        "friss hírek",
        "friss hirek",
        "aktuális ár",
        "aktualis ar",
        "most mennyi",
        "look up",
        "search for",
        "search the web",
        "find online",
        "browse the web",
        "latest news",
        "current price",
        "eur",
        "€",
        "ár alatt",
        "ar alatt",
        "mennyiért",
        "mennyiert",
        "kapható",
        "kaphato",
        "elérhető",
        "elerheto",
        "ajánlat",
        "ajanlat",
        "hol lehet venni",
        "hol kapok",
        "vásárlás",
        "vasarlas",
        "buy",
        "price",
        "under €",
        "under eur",
        "in stock",
        "available now",
    ]
    return (
        any(marker in normalized for marker in markers)
        or bool(re.search(r"\bkeress\w*\b", normalized, flags=re.IGNORECASE))
    )
