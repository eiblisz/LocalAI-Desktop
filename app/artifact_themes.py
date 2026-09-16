from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactTheme:
    key: str
    label: str
    family: str
    executive: bool
    accent: str
    accent_dark: str
    accent_light: str
    text: str
    muted: str
    surface: str
    border: str
    zebra: str
    hero_foreground: str
    hero_subtle: str
    print_friendly: bool = True


THEMES = {
    "red_professional": ArtifactTheme(
        key="red_professional",
        label="Red Professional",
        family="red",
        executive=False,
        accent="B92F3B",
        accent_dark="8E1F2D",
        accent_light="F9EDEF",
        text="1F2630",
        muted="6C737F",
        surface="F4F6F8",
        border="D9DEE5",
        zebra="FAFBFC",
        hero_foreground="FFFFFF",
        hero_subtle="FFE9EC",
    ),
    "red_executive": ArtifactTheme(
        key="red_executive",
        label="Red Executive",
        family="red",
        executive=True,
        accent="B92F3B",
        accent_dark="8E1F2D",
        accent_light="F9EDEF",
        text="1F2630",
        muted="6C737F",
        surface="F4F6F8",
        border="D9DEE5",
        zebra="FAFBFC",
        hero_foreground="FFFFFF",
        hero_subtle="FFE9EC",
    ),
    "classic_professional": ArtifactTheme(
        key="classic_professional",
        label="Classic Professional",
        family="classic",
        executive=False,
        accent="44546A",
        accent_dark="2F3A4A",
        accent_light="EEF1F4",
        text="20252B",
        muted="6B737C",
        surface="F6F7F8",
        border="D7DBE0",
        zebra="FAFAFA",
        hero_foreground="FFFFFF",
        hero_subtle="E7EBF0",
    ),
    "classic_executive": ArtifactTheme(
        key="classic_executive",
        label="Classic Executive",
        family="classic",
        executive=True,
        accent="44546A",
        accent_dark="2F3A4A",
        accent_light="EEF1F4",
        text="20252B",
        muted="6B737C",
        surface="F6F7F8",
        border="D7DBE0",
        zebra="FAFAFA",
        hero_foreground="FFFFFF",
        hero_subtle="E7EBF0",
    ),
    "red_workbook": ArtifactTheme(
        key="red_workbook",
        label="Red Executive Workbook",
        family="red",
        executive=True,
        accent="B92F3B",
        accent_dark="8E1F2D",
        accent_light="F9EDEF",
        text="1F2630",
        muted="6C737F",
        surface="F4F6F8",
        border="D9DEE5",
        zebra="FAFBFC",
        hero_foreground="FFFFFF",
        hero_subtle="FFE9EC",
    ),
    "classic_workbook": ArtifactTheme(
        key="classic_workbook",
        label="Classic Workbook",
        family="classic",
        executive=True,
        accent="44546A",
        accent_dark="2F3A4A",
        accent_light="EEF1F4",
        text="20252B",
        muted="6B737C",
        surface="F6F7F8",
        border="D7DBE0",
        zebra="FAFAFA",
        hero_foreground="FFFFFF",
        hero_subtle="E7EBF0",
    ),
}

LABEL_TO_KEY = {theme.label: key for key, theme in THEMES.items()}


def get_theme(name: str) -> ArtifactTheme:
    key = LABEL_TO_KEY.get(name, name)
    try:
        return THEMES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown artifact theme: {name}") from exc


def document_preset_labels() -> list[str]:
    return [
        THEMES["red_professional"].label,
        THEMES["red_executive"].label,
        THEMES["classic_professional"].label,
        THEMES["classic_executive"].label,
    ]


def workbook_preset_labels() -> list[str]:
    return [
        THEMES["red_workbook"].label,
        THEMES["classic_workbook"].label,
    ]
