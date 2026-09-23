"""Versioned deterministic Hungarian request lexicon.

It classifies question *shape*, not named entities.  The entries are canonical
(accent-insensitive) matching phrases consumed by :mod:`question_semantics`.
"""

LEXICON_VERSION = 2

REQUESTED_FACT_MARKERS = {
    "definition": ("mi az a", "mit jelent", "mi a jelentese", "what is", "definition"),
    "year": ("melyik evben", "mely evben", "hanyban", "what year"),
    "temporal": (
        "mikor", "mikorra", "mikortol", "miota", "meddig", "date", "year", "when",
    ),
    "location": (
        "hol talalhato", "hol", "hova", "honnan", "merre", "where", "location", "place",
    ),
    "cause": ("miert", "mi okbol", "mitol", "mi miatt", "mi oka", "why", "cause"),
    "method": ("hogyan", "mikent", "milyen modon", "how", "method"),
    "process": ("folyamata", "mik a lepesei", "process"),
    "price": ("mennyi az ara", "mennyibe kerul", "price", "cost"),
    "quantity": ("mennyi", "hany", "mekkora", "how many", "how much", "quantity"),
    "selection": ("melyik", "mely", "melyiket", "melyek", "which", "choose"),
    "attribute": ("milyen", "mifele", "milyen fajta", "milyen tipusu"),
    "owner": ("kie", "ki a tulajdonosa", "owner"),
    "means": ("mivel", "mi altal", "by what means"),
    "duration": ("mennyi ideig", "meddig", "duration"),
    "frequency": ("milyen gyakran", "hanyszor", "frequency"),
    "status": ("elerheto", "kaphato", "allapota", "available", "status"),
    "boolean": (
        "van e", "volt e", "igaz e", "lehet e", "tud e", "mukodik e",
        "does", "is it", "can",
    ),
    "version": ("verzioja", "verzio", "kiadasa", "valtozata", "version", "release"),
    "current_value": ("most", "jelenlegi", "aktualis", "mai", "current", "latest"),
    "comparison": ("kulonbseg", "hasonlosag", "compare", "comparison"),
    "person_relation": (
        "ki", "kit", "kinek", "kirol", "kivel", "kinel", "kitol", "kik",
        "szerzo", "author", "creator", "founder", "who",
    ),
    "entity": ("mi", "mit", "minek", "mirol", "miben", "mibol", "what"),
}

RELATION_MARKERS = {
    "authorship": ("irta", "megirta", "szerzoje", "irta meg", "wrote", "authored"),
    "creation": (
        "keszitette", "alkotta", "megalkotta", "letrehozta", "composed", "created",
    ),
    "founding": ("alapitotta", "megalapitotta", "founded by"),
    "formation": (
        "alakult", "megalakult", "letrejott", "osszeallt", "formed", "founded", "established",
    ),
    "identity": ("ki ", "who is", "mi az", "what is"),
    "leadership": ("vezeti", "vezetoje", "iranyitja", "elen all", "leader", "president"),
    "role_member": (
        "frontembere", "enekese", "gitarosa", "dobosa", "tagja", "member", "members",
    ),
    "birth": ("szuletett", "born", "birth"),
    "death": ("meghalt", "halt meg", "died", "death"),
    "release": ("megjelent", "jelent meg", "kiadtak", "bemutattak", "released"),
    "publication": ("publikaltak", "kiadtak", "published"),
    "event_date": ("tortent", "esemeny", "happened", "event"),
    "location": ("hol", "where", "helye"),
    "origin": ("honnan", "szarmazik", "origin", "from where"),
    "ownership": ("kie", "tulajdonos", "owner", "ownership"),
    "price": ("ara", "kerul", "mennyit er", "price", "cost"),
    "current_price": ("aktualis ara", "jelenlegi ara", "current price"),
    "version": ("verzio", "kiadas", "version", "release"),
    "duration": ("meddig", "mennyi ideig", "duration", "long"),
    "cause": ("miert", "why", "cause"),
    "purpose": ("mire valo", "celja", "purpose", "for what"),
    "age": ("hany eves", "eletkora", "age"),
    "size": ("mekkora", "merete", "size"),
    "distance": ("milyen messze", "tavolsag", "distance"),
    "function": ("hogyan mukodik", "mit csinal", "feladata", "function", "works"),
    "composition": ("mibol all", "osszetetele", "composition"),
    "succession": ("utodja", "elozo", "kovette", "successor"),
    "relationship": ("kapcsolata", "rokona", "relationship"),
    "comparison": (
        "hasonlitsd ossze", "vesd ossze", "kulonbseg", "hasonlosag", "compare",
        "versus", "vs",
    ),
    "recommendation": ("ajanlj", "melyiket", "recommend", "should i"),
    "availability": ("elerheto", "kaphato", "available"),
    "dissolution": ("feloszlott", "megszunt", "dissolved", "ended"),
    "change": ("mikor valtozott", "changed", "change"),
    "discovery": (
        "keress", "keresd meg", "nezz utana", "ajanlj", "javasolj",
        "felfedezte", "discovered", "discovery",
    ),
}

DEPTH_MARKERS = {
    "concise": ("roviden", "tomoren", "par szoban", "csak a lenyeget"),
    "overview": ("mit tudsz rola", "meselj rola", "mutasd be", "adj attekintest"),
    "detailed": ("reszletesen", "bovebben", "alaposan", "melyebben", "atfogoan"),
    "analysis": ("elemezd", "vizsgald meg", "ertekeld", "bontsd ki"),
}

FRESHNESS_MARKERS = {
    "current": (
        "most", "jelenleg", "aktualis", "mai", "ma", "legfrissebb", "legujabb",
        "jelenlegi", "mostani",
    ),
    "recent": ("mostanaban", "utobbi idoben", "friss"),
    "historical": ("korabban", "regen", "eredetileg", "tortenelmileg"),
}
