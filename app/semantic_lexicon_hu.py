"""Small deterministic Hungarian question lexicon.

It classifies question *shape*, not named entities.  The entries are canonical
(accent-insensitive) matching phrases consumed by :mod:`question_semantics`.
"""

REQUESTED_FACT_MARKERS = {
    "temporal": ("mikor", "melyik evben", "milyen evben", "date", "year", "when"),
    "location": ("hol", "honnan", "where", "location", "place"),
    "quantity": ("mennyi", "hany", "how many", "how much", "quantity", "count"),
    "current_value": ("most", "jelenlegi", "aktualis", "current", "latest", "price"),
    "version": ("verzio", "kiadas", "version", "release"),
    "cause": ("miert", "mi oka", "why", "cause"),
    "method": ("hogyan", "milyen modon", "how", "method", "process"),
    "definition": ("mi az", "mit jelent", "what is", "definition"),
    "selection": ("melyik", "which", "choose", "recommended"),
    "status": ("elerheto", "kaphato", "available", "status"),
    "boolean": ("igaz e", "van e", "does", "is it", "can"),
    "person_relation": ("ki", "szerzo", "author", "creator", "founder", "who"),
}

RELATION_MARKERS = {
    "creation": ("irta", "megirta", "alkotta", "keszitette", "wrote", "authored", "composed", "created"),
    "formation": ("alakult", "megalakult", "letrejott", "formed", "founded", "established"),
    "identity": ("ki ", "who is", "mi az", "what is"),
    "leadership": ("vezeto", "elnok", "leader", "president"),
    "membership": ("tagja", "tagok", "member", "members"),
    "birth": ("szuletett", "born", "birth"),
    "death": ("meghalt", "halt meg", "died", "death"),
    "release": ("jelent meg", "kiadtak", "released", "published"),
    "event_date": ("tortent", "esemeny", "happened", "event"),
    "location": ("hol", "where", "helye"),
    "origin": ("honnan", "szarmazik", "origin", "from where"),
    "ownership": ("kie", "tulajdonos", "owner", "ownership"),
    "price": ("ar", "mennyibe", "price", "cost"),
    "version": ("verzio", "kiadas", "version", "release"),
    "duration": ("meddig", "mennyi ideig", "duration", "long"),
    "cause": ("miert", "why", "cause"),
    "purpose": ("mire valo", "celja", "purpose", "for what"),
    "function": ("hogyan mukodik", "function", "works"),
    "comparison": ("hasonlitsd", "kulonbseg", "compare", "versus"),
    "recommendation": ("ajanlj", "melyiket", "recommend", "should i"),
    "availability": ("elerheto", "kaphato", "available"),
    "dissolution": ("feloszlott", "megszunt", "dissolved", "ended"),
    "change": ("mikor valtozott", "changed", "change"),
    "discovery": ("felfedezte", "discovered", "discovery"),
}
