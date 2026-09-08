"""Vocabulários e roteamento conservador."""

from __future__ import annotations

from .util import ascii_fold


PRODUCT_THEORY = "CURSO_DE_TEORIA"
PRODUCT_SOLUTIONS = "CURSO_DE_RESOLUCOES_DE_EXERCICIOS"
PRODUCTS = {PRODUCT_THEORY, PRODUCT_SOLUTIONS}

CLASSIFICATIONS = (
    "EXATO",
    "EQUIVALENTE_RIGOROSO",
    "PARCIAL",
    "TEORIA_APENAS",
    "ERRO_MATEMATICO",
    "NAO_VERIFICAVEL",
    "NAO_ENCONTRADO",
)

APPROVED_CLASSIFICATIONS = {"EXATO", "EQUIVALENTE_RIGOROSO"}

INTERNAL_INSPECTIONS = {"TRANSCRICAO", "FALA_VERIFICADA", "FRAME", "DIRETA"}
SPEECH_INSPECTIONS = {"TRANSCRICAO", "FALA_VERIFICADA", "DIRETA"}
VISUAL_INSPECTIONS = {"FRAME", "DIRETA"}

PROFILE_KEYWORDS = {
    "MATEMATICA": (
        "matemat",
        "algebra",
        "calculo",
        "geometr",
        "topolog",
        "teorema",
        "grafo",
        "vertice",
        "aresta",
    ),
    "ESTATISTICA_PROBABILIDADE": ("estatistic", "probabil", "distribuicao", "inferenc", "regress"),
    "FISICA": ("fisica", "mecanica", "eletromagnet", "termodinam", "quantica"),
    "QUIMICA": ("quimica", "molecula", "reacao", "estequiometr", "organica"),
    "BIOLOGIA_SAUDE": ("biologia", "celula", "genetic", "ecologia", "anatom", "fisiolog"),
    "COMPUTACAO": ("python", "program", "algoritm", "software", "banco de dados", "codigo"),
    "ENGENHARIA": ("engenharia", "circuito", "controle", "estruturas", "processo industrial"),
    "LINGUAS_LITERATURA": ("lingua", "linguistic", "literatura", "gramatica", "redacao", "poesia"),
    "HISTORIA": ("historia", "historico", "revolucao", "imperio", "colonial"),
    "CIENCIAS_SOCIAIS": ("sociologia", "antropologia", "sociedade", "politica", "cultura"),
    "DIREITO": ("direito", "lei", "juridic", "constitucional", "contrato"),
    "ECONOMIA_NEGOCIOS": ("economia", "financas", "mercado", "contabilidade", "gestao"),
    "PSICOLOGIA_COMPORTAMENTO": ("psicologia", "comportamento", "cognitiv", "emocao", "terapia"),
    "MEDICINA_SAUDE": ("medicina", "doenca", "tratamento", "diagnostico", "sintoma", "clinico"),
    "ARTES": ("arte", "musica", "pintura", "cinema", "design", "teatro"),
}

SENSITIVE_KEYWORDS = (
    "compulsao",
    "suicid",
    "automutil",
    "transtorno",
    "diagnostico",
    "tratamento",
    "medicamento",
    "doenca",
    "juridic",
    "investimento",
    "violencia",
)

EXERCISE_MARKERS = (
    "exercicio",
    "questao",
    "problema",
    "prove que",
    "demonstre",
    "calcule",
    "resolva",
    "mostre que",
)


def choose_profile(text: str) -> str:
    folded = ascii_fold(text)
    scores = {
        profile: sum(1 for keyword in keywords if keyword in folded)
        for profile, keywords in PROFILE_KEYWORDS.items()
    }
    best = max(scores, key=lambda profile: scores[profile], default="UNIVERSAL")
    return best if scores.get(best, 0) else "UNIVERSAL"


def detect_safety_overlay(text: str) -> str:
    folded = ascii_fold(text)
    return "SENSIVEL" if any(word in folded for word in SENSITIVE_KEYWORDS) else "ROTINA"


def detect_product(text: str) -> str:
    folded = ascii_fold(text)
    matches = sum(1 for marker in EXERCISE_MARKERS if marker in folded)
    return PRODUCT_SOLUTIONS if matches else PRODUCT_THEORY
