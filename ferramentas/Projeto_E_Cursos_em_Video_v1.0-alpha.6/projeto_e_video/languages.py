"""Política explícita de busca mundial e normalização de idiomas."""

from __future__ import annotations

import re
from typing import Final

from .models import PRODUCT_SOLUTIONS


TARGET_AUDIO_LANGUAGES: Final[tuple[str, str]] = ("pt", "en")

# Sementes não constituem a lista de idiomas humanos. Elas tornam a busca
# automática útil sem API de tradução; o prompt GLOBAL_OPEN manda o navegador
# ampliar para qualquer idioma relevante e registrar o que realmente tentou.
GLOBAL_QUERY_SEEDS: Final[tuple[tuple[str, str, str], ...]] = (
    ("pt", "resolução passo a passo", "aula completa com exemplos"),
    ("en", "step by step solved exercise", "full lecture with examples"),
    ("es", "ejercicio resuelto paso a paso", "clase completa con ejemplos"),
    ("fr", "exercice corrigé étape par étape", "cours complet avec exemples"),
    ("de", "Aufgabe Schritt für Schritt gelöst", "vollständige Vorlesung mit Beispielen"),
    ("it", "esercizio svolto passo dopo passo", "lezione completa con esempi"),
    ("nl", "uitgewerkte oefening stap voor stap", "volledige les met voorbeelden"),
    ("pl", "zadanie rozwiązane krok po kroku", "pełny wykład z przykładami"),
    ("cs", "řešený příklad krok za krokem", "úplná přednáška s příklady"),
    ("ro", "exercițiu rezolvat pas cu pas", "lecție completă cu exemple"),
    ("hu", "megoldott feladat lépésről lépésre", "teljes előadás példákkal"),
    ("sv", "löst uppgift steg för steg", "fullständig lektion med exempel"),
    ("da", "løst opgave trin for trin", "komplet lektion med eksempler"),
    ("no", "løst oppgave trinn for trinn", "fullstendig undervisning med eksempler"),
    ("fi", "ratkaistu tehtävä vaihe vaiheelta", "täydellinen oppitunti esimerkeillä"),
    ("el", "λυμένη άσκηση βήμα προς βήμα", "πλήρες μάθημα με παραδείγματα"),
    ("ru", "решение задачи шаг за шагом", "полная лекция с примерами"),
    ("uk", "розв'язання задачі крок за кроком", "повна лекція з прикладами"),
    ("tr", "adım adım çözümlü soru", "örneklerle tam ders"),
    ("ar", "حل تمرين خطوة بخطوة", "درس كامل مع أمثلة"),
    ("he", "פתרון תרגיל שלב אחר שלב", "שיעור מלא עם דוגמאות"),
    ("fa", "حل تمرین گام به گام", "درس کامل با مثال"),
    ("hi", "चरण दर चरण हल किया गया प्रश्न", "उदाहरणों सहित पूरा पाठ"),
    ("bn", "ধাপে ধাপে সমাধান করা অনুশীলন", "উদাহরণসহ পূর্ণ পাঠ"),
    ("ur", "مرحلہ وار حل شدہ سوال", "مثالوں کے ساتھ مکمل سبق"),
    ("zh-Hans", "习题逐步讲解", "完整课程与例题"),
    ("zh-Hant", "習題逐步講解", "完整課程與例題"),
    ("ja", "演習問題をステップごとに解説", "例題付き完全講義"),
    ("ko", "연습문제 단계별 풀이", "예제가 포함된 전체 강의"),
    ("id", "soal diselesaikan langkah demi langkah", "pelajaran lengkap dengan contoh"),
    ("ms", "latihan diselesaikan langkah demi langkah", "pelajaran lengkap dengan contoh"),
    ("vi", "bài tập giải từng bước", "bài giảng đầy đủ có ví dụ"),
    ("th", "โจทย์พร้อมวิธีทำทีละขั้นตอน", "บทเรียนฉบับเต็มพร้อมตัวอย่าง"),
    ("sw", "zoezi lililotatuliwa hatua kwa hatua", "somo kamili lenye mifano"),
)

_TAG = re.compile(
    r"^(?:und|[A-Za-z]{2,3})(?:-(?:[A-Za-z]{4}|[A-Za-z]{2}|[0-9]{3}|[A-Za-z0-9]{5,8}))*$"
)


def normalize_language_tag(value: object, *, default: str = "und") -> str:
    """Normaliza o subconjunto útil de BCP 47 sem inventar um idioma."""

    if not isinstance(value, str) or not value.strip():
        return default
    raw = value.strip().replace("_", "-")
    if not _TAG.fullmatch(raw):
        raise ValueError(f"tag de idioma inválida: {value!r}")
    parts = raw.split("-")
    if parts[0].lower() == "und":
        return "und"
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def normalize_provider_language_tag(
    value: object,
) -> tuple[str, str | None, str | None]:
    """Tolera sufixos privados de provedores sem afrouxar entradas canônicas."""

    if not isinstance(value, str) or not value.strip():
        return "und", None, None
    raw = value.strip()
    try:
        return normalize_language_tag(raw), raw, None
    except ValueError:
        parts = raw.replace("_", "-").split("-")
        trusted = parts[:1]
        if len(parts) > 1 and len(parts[1]) == 4 and parts[1].isalpha():
            trusted.append(parts[1])
        region_index = len(trusted)
        if len(parts) > region_index and (
            (len(parts[region_index]) == 2 and parts[region_index].isalpha())
            or (len(parts[region_index]) == 3 and parts[region_index].isdigit())
        ):
            trusted.append(parts[region_index])
        try:
            normalized = normalize_language_tag("-".join(trusted))
        except ValueError:
            normalized = "und"
        if normalized != "und":
            return (
                normalized,
                raw,
                f"tag interna do provedor {raw!r} reduzida ao prefixo BCP-47 {normalized!r}",
            )
        return (
            "und",
            raw,
            f"tag interna do provedor {raw!r} não possui prefixo BCP-47 confiável",
        )


def language_family(value: object) -> str:
    return normalize_language_tag(value).split("-", 1)[0]


def is_target_audio_language(value: object) -> bool:
    return language_family(value) in TARGET_AUDIO_LANGUAGES


def query_action(language: str, product: str) -> str:
    normalized = normalize_language_tag(language)
    for tag, solution, theory in GLOBAL_QUERY_SEEDS:
        if tag == normalized:
            return solution if product == PRODUCT_SOLUTIONS else theory
    raise ValueError(f"idioma sem semente de consulta: {language}")


def global_seed_languages() -> list[str]:
    return [row[0] for row in GLOBAL_QUERY_SEEDS]
