"""Lightweight i18n for the web UI.

Design: the Swedish source string *is* the translation key. Wrapping a
string as ``{{ t("Plånböcker") }}`` renders it in Swedish by default; when
the active language is English and a translation exists, the English text
is returned instead. Anything not yet translated simply stays Swedish, so
templates can be internationalised incrementally without breaking.

The active language is stored in a ``contextvars.ContextVar`` set per
request by ``LocaleMiddleware`` from the ``lang`` cookie, so templates can
call the global ``t()`` without every route threading a language through.
"""

from contextvars import ContextVar

DEFAULT_LANG = "sv"
SUPPORTED_LANGS = ("sv", "en")

_current_lang: ContextVar[str] = ContextVar("current_lang", default=DEFAULT_LANG)

# English translations keyed by the Swedish source string.
# Missing keys fall back to the Swedish source (graceful, incremental).
TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # ── Navigation / chrome ──
        "Dashboard": "Dashboard",
        "Plånböcker": "Wallets",
        "Importera": "Import",
        "Åtgärder": "Actions",
        "Adresser": "Addresses",
        "Priser": "Prices",
        "Inställningar": "Settings",
        "Logga ut": "Log out",
        "Logga in": "Log in",
        "Stöd projektet": "Support the project",
        "Gå till dashboard": "Go to dashboard",
        "Huvudnavigation": "Main navigation",
        "Källkod på GitHub": "Source code on GitHub",
        "Språk": "Language",
        "Svenska": "Swedish",
        "Engelska": "English",
        # ── Dashboard ──
        "Skatteår": "Tax years",
        "Översikt": "Overview",
        "Inga skatteår ännu": "No tax years yet",
        "Registrerade plånböcker": "Registered wallets",
        "Senaste import": "Last import",
        "Kom igång": "Get started",
        "Beräkna": "Calculate",
        "Vinster": "Gains",
        "Förluster": "Losses",
        "Netto": "Net",
        "Antal avyttringar": "Number of disposals",
        # ── Common actions / labels ──
        "Ladda ner": "Download",
        "Spara": "Save",
        "Ta bort": "Delete",
        "Avbryt": "Cancel",
        "Lägg till": "Add",
        "Sök": "Search",
        "Kedja": "Chain",
        "Adress": "Address",
        "Label": "Label",
        "Kategori": "Category",
        "Belopp": "Amount",
        "Datum": "Date",
        "Coin": "Coin",
        "Tillgång": "Asset",
        # ── Reward types ──
        "Staking": "Staking",
        "Mining": "Mining",
        "Airdrop": "Airdrop",
        "Ränta": "Interest",
        "Belöning": "Reward",
    },
}


def set_language(lang: str) -> None:
    _current_lang.set(lang if lang in SUPPORTED_LANGS else DEFAULT_LANG)


def get_language() -> str:
    return _current_lang.get()


def translate(text: str) -> str:
    """Translate a Swedish source string to the active language."""
    lang = _current_lang.get()
    if lang == DEFAULT_LANG:
        return text
    return TRANSLATIONS.get(lang, {}).get(text, text)
