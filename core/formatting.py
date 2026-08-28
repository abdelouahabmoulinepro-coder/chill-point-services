from __future__ import annotations

from datetime import date, datetime


DOCUMENT_LABELS = {
    "DEVIS": "Devis",
    "PROFORMA": "Facture proforma",
    "FACTURE": "Facture",
    "BL": "Bon de livraison",
}

DOCUMENT_PATTERNS = {
    "DEVIS": "EST-{seq:06d}",
    "PROFORMA": "PRO-{year}/{seq:06d}",
    "FACTURE": "FA-{year}/{seq:06d}",
    "BL": "BL-{year}/{seq:06d}",
}

STATUS_OPTIONS = {
    "DEVIS": ["Brouillon", "Envoyé", "Accepté", "Refusé", "Expiré"],
    "PROFORMA": ["Brouillon", "Envoyée", "Acceptée", "Expirée"],
    "FACTURE": [
        "Brouillon",
        "Envoyée",
        "Partiellement payée",
        "Payée",
        "En retard",
        "Annulée",
    ],
    "BL": ["Brouillon", "Préparé", "Livré"],
}


def money(value: float | int | None, currency: str = "EUR") -> str:
    amount = float(value or 0)
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    label = {"MAD": "DH"}.get(currency, currency)
    return f"{formatted} {label}"


def _under_hundred(number: int) -> str:
    units = [
        "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf",
        "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
    ]
    if number < 17:
        return units[number]
    if number < 20:
        return "dix-" + units[number - 10]
    if number < 70:
        tens = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante"}
        base = number // 10 * 10
        rest = number % 10
        if rest == 0:
            return tens[base]
        connector = " et " if rest == 1 else "-"
        return tens[base] + connector + units[rest]
    if number < 80:
        rest = number - 60
        return "soixante et onze" if rest == 11 else "soixante-" + _under_hundred(rest)
    rest = number - 80
    if rest == 0:
        return "quatre-vingts"
    return "quatre-vingt-" + _under_hundred(rest)


def _under_thousand(number: int) -> str:
    if number < 100:
        return _under_hundred(number)
    hundreds, rest = divmod(number, 100)
    prefix = "cent" if hundreds == 1 else f"{_under_hundred(hundreds)} cent"
    if rest == 0:
        return prefix + ("s" if hundreds > 1 else "")
    return f"{prefix} {_under_hundred(rest)}"


def number_in_words_fr(number: int) -> str:
    if number == 0:
        return "zéro"
    if number < 0:
        return "moins " + number_in_words_fr(abs(number))
    parts: list[str] = []
    scales = [(1_000_000_000, "milliard"), (1_000_000, "million"), (1_000, "mille")]
    remainder = number
    for scale, label in scales:
        count, remainder = divmod(remainder, scale)
        if not count:
            continue
        if scale == 1_000 and count == 1:
            parts.append("mille")
        else:
            plural = "s" if count > 1 and scale != 1_000 else ""
            parts.append(f"{_under_thousand(count)} {label}{plural}")
    if remainder:
        parts.append(_under_thousand(remainder))
    return " ".join(parts)


def amount_in_words(value: float, currency: str) -> str:
    rounded = round(float(value) + 1e-9, 2)
    whole = int(rounded)
    cents = int(round((rounded - whole) * 100))
    if currency == "MAD":
        main_unit = "dirham" if whole == 1 else "dirhams"
        cent_unit = "centime" if cents == 1 else "centimes"
    else:
        main_unit = currency
        cent_unit = "centime" if cents == 1 else "centimes"
    result = f"{number_in_words_fr(whole)} {main_unit}"
    if cents:
        result += f" et {number_in_words_fr(cents)} {cent_unit}"
    return result.upper()


def french_date(value: str | date | datetime | None) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d/%m/%Y")


def document_label(doc_type: str) -> str:
    return DOCUMENT_LABELS.get(doc_type, doc_type)
