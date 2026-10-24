#!/usr/bin/env python3
"""Prototipo de operacoes somente leitura, usando exclusivamente o pathguard.

NAO e um launcher de agentes, CLI, substituto para o SRT ou prova de STRONG.
O chamador futuro deve abrir o descritor com pathguard.open_root APOS validar a
configuracao e executar o processo todo sob a fronteira do SRT. Nunca oferecer
Read/Grep/Glob nativos em paralelo a esta interface restrita.

Nenhuma operacao de escrita, shell, rede, subprocesso, caminho absoluto ou
opcao de bypass e disponibilizada por este modulo.
"""
import json
import os
import stat

import pathguard


MAX_REQUEST_BYTES = 4096
MAX_READ_BYTES = 65536
MAX_LIST_ENTRIES = 1024
MAX_SCAN_ENTRIES = 20000


class RequestDenied(ValueError):
    """Recusa estavel sem revelar conteudos/caminhos do workspace."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RequestDenied("duplicate_key")
        result[key] = value
    return result


def _non_json_constant(_value):
    raise RequestDenied("invalid_json")


def parse_request(raw):
    """Recebe um unico JSON UTF-8 estrito e exige o contrato fechado."""
    if type(raw) is not bytes or not (0 < len(raw) <= MAX_REQUEST_BYTES):
        raise RequestDenied("invalid_request_size")
    try:
        data = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_non_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise RequestDenied("invalid_json") from None
    _validate_request(data)
    return data


def _validate_request(request):
    if type(request) is not dict:
        raise RequestDenied("invalid_request")
    op = request.get("op")
    keys = set(request)
    if op == "read":
        if keys != {"op", "path"}:
            raise RequestDenied("invalid_fields")
    elif op == "list":
        if keys not in ({"op"}, {"op", "path"}):
            raise RequestDenied("invalid_fields")
    else:
        raise RequestDenied("operation_denied")

    if "path" in request:
        path = request["path"]
        if type(path) is not str:
            raise RequestDenied("invalid_path")
        try:
            pathguard.split_relpath(path)
        except pathguard.PathGuardError:
            raise RequestDenied("invalid_path") from None


def dispatch(root_fd, request):
    """Executa somente read/list em FD aprovado; NAO abre caminhos de raiz.

    O root_fd deve ter sido obtido via pathguard.open_root sobre uma pasta
    explicitamente autorizada. Revarre a arvore antes de cada chamada, para
    recusar links/perifericos que ja existam. A varredura nao impede races,
    bind mounts no mesmo dispositivo nem acesso fora deste modulo.
    """
    _validate_request(request)
    if type(root_fd) is not int:
        raise RequestDenied("invalid_root")
    try:
        if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
            raise RequestDenied("invalid_root")
        findings = pathguard.scan_tree(root_fd, max_entries=MAX_SCAN_ENTRIES)
        if findings:
            raise RequestDenied("unsafe_tree")
        op = request["op"]
        if op == "read":
            raw = pathguard.read_bytes(root_fd, request["path"], max_bytes=MAX_READ_BYTES)
            try:
                decoded = raw.decode("utf-8", "strict")
            except UnicodeDecodeError:
                raise RequestDenied("invalid_encoding") from None
            return {"ok": True, "op": "read", "text": decoded}
        path = request.get("path")
        names = pathguard.list_dir(root_fd, path)
        if len(names) > MAX_LIST_ENTRIES:
            raise RequestDenied("too_many_entries")
        return {"ok": True, "op": "list", "entries": names}
    except pathguard.PathGuardError:
        raise RequestDenied("path_denied") from None
    except OSError:
        raise RequestDenied("filesystem_error") from None


def dispatch_json(root_fd, raw):
    """Composicao de parser e dispatcher para testes de fixture sintetica."""
    return dispatch(root_fd, parse_request(raw))
