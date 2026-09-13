"""Validação conservadora de URLs antes de qualquer acesso de rede."""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse


AUTOMATED_VIDEO_HOST_SUFFIXES = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
)


def _public_ip(address: str) -> None:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ValueError(f"endereço resolvido inválido: {address}") from exc
    if not parsed.is_global:
        raise ValueError("URL aponta rede privada, local ou reservada")


def validate_http_url(url: str, *, resolve: bool = False) -> urllib.parse.SplitResult:
    """Valida sintaxe e, quando solicitado, todos os endereços DNS observados."""

    if not isinstance(url, str) or not url.strip() or len(url) > 4096:
        raise ValueError("URL de rede ausente ou excessiva")
    if any(ord(character) < 32 for character in url):
        raise ValueError("URL de rede contém caractere de controle")
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL de rede deve usar HTTP ou HTTPS com host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL de rede não pode conter credenciais")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("porta inválida na URL") from exc
    if port is not None and port not in {80, 443}:
        raise ValueError("URL de rede usa porta não permitida")
    host = parsed.hostname.rstrip(".").lower()
    if (
        host == "localhost"
        or host.endswith((".localhost", ".local", ".internal", ".home.arpa"))
    ):
        raise ValueError("URL aponta host local ou interno")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise ValueError("URL aponta rede privada, local ou reservada")
    if not resolve:
        return parsed
    try:
        addresses = {
            str(item[4][0])
            for item in socket.getaddrinfo(
                host,
                port or (443 if parsed.scheme.lower() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except (socket.gaierror, UnicodeError) as exc:
        raise ValueError(f"não foi possível resolver o host da URL: {exc}") from exc
    if not addresses:
        raise ValueError("host da URL não possui endereço resolvido")
    for address in addresses:
        _public_ip(address)
    return parsed


def validate_public_network_url(url: str) -> None:
    """Autoriza uma URL pública geral para a ingestão controlada."""

    validate_http_url(url, resolve=True)


def validate_automated_video_url(url: str) -> None:
    """Autoriza coleta automática apenas em plataformas públicas conhecidas."""

    parsed = validate_http_url(url, resolve=True)
    host = (parsed.hostname or "").rstrip(".").lower()
    if not any(
        host == suffix or host.endswith("." + suffix)
        for suffix in AUTOMATED_VIDEO_HOST_SUFFIXES
    ):
        raise ValueError(
            "coleta automática aceita somente plataformas públicas conhecidas; "
            "inspecione este candidato diretamente no navegador"
        )
