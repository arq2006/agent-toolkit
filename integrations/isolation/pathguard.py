#!/usr/bin/env python3
"""Guarda de caminhos para o executor (GH-F1.8, ADR-011). Proposta; nada aqui é isolamento.

Só biblioteca padrão (Python 3.11+). Sem shell, sem rede, sem subprocessos.

O que faz: valida caminhos relativos e opera sob uma pasta autorizada já aberta (descritor
`root_fd`), percorrendo componente a componente com `dir_fd` + `O_NOFOLLOW` e conferindo `fstat`
no objeto aberto (arquivo regular, `st_nlink == 1`, mesmo dispositivo da raiz).

O que NÃO faz: não isola processo algum. Protege apenas operações feitas por este módulo; agentes
com Read/Edit nativos não passam por aqui. Não elimina TOCTOU contra processos externos que
alterem a pasta concorrentemente, e hardlinks criados fora deste módulo só são vistos na
verificação. Nenhum ambiente é classificado como STRONG por este módulo.

Riscos concorrentes que permanecem (não resolvidos aqui): processo externo que troque componentes
do caminho entre duas operações; hardlinks criados após a checagem de `st_nlink`; bind mounts e
pontos de montagem dentro da pasta (só o `st_dev` é comparado, e bind mount do mesmo dispositivo
não é detectado); ferramentas Read/Edit nativas, que não passam por este módulo.

Falha sempre fechada: qualquer dúvida, plataforma sem suporte ou erro de SO vira PathGuardError.
"""
import os
import stat

try:
    import pwd
except ImportError:  # plataforma sem banco de contas: a raiz será recusada
    pwd = None

MAX_PATH = 4096
MAX_COMPONENT = 255
DEFAULT_MAX_READ = 1_048_576


class PathGuardError(Exception):
    """Operação recusada. Mensagens não incluem conteúdo de arquivos."""


def _require_platform():
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise PathGuardError("plataforma sem O_NOFOLLOW/O_DIRECTORY: recusado")
    if os.open not in os.supports_dir_fd:
        raise PathGuardError("plataforma sem suporte a dir_fd: recusado")


def split_relpath(rel):
    """Valida um caminho relativo textual e devolve seus componentes."""
    if not isinstance(rel, str):
        raise PathGuardError("caminho deve ser texto")
    if not rel:
        raise PathGuardError("caminho vazio")
    if "\x00" in rel:
        raise PathGuardError("caminho contém NUL")
    if len(rel) > MAX_PATH:
        raise PathGuardError("caminho longo demais")
    if rel.startswith("/") or "\\" in rel or (len(rel) > 1 and rel[1] == ":"):
        raise PathGuardError("caminho absoluto ou com separador/unidade não permitido")
    parts = rel.split("/")
    for p in parts:
        if p == "":
            raise PathGuardError("componente vazio (// ou / final)")
        if p in (".", ".."):
            raise PathGuardError("componente '.' ou '..' não permitido")
        if len(p) > MAX_COMPONENT:
            raise PathGuardError("componente longo demais")
    return tuple(parts)


def account_home():
    """Home da conta Linux efetiva, pelo banco de contas do SO (nunca pela variável HOME).
    Sem como determinar com segurança, recusa."""
    if pwd is None:
        raise PathGuardError("banco de contas indisponível: não é possível proteger a home")
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError):
        raise PathGuardError("conta do usuário não encontrada: não é possível proteger a home") from None
    if not isinstance(home, str) or not home or "\x00" in home or not os.path.isabs(home):
        raise PathGuardError("home da conta indeterminada: recusado")
    return home


def _protected_homes():
    home = account_home()
    return {os.path.normpath(home), os.path.realpath(home)}


def check_authorized_path(path):
    """Validação textual de uma pasta autorizada; devolve os componentes. Recusa não absoluto,
    NUL, '/', componentes vazios/'.'/'..' (inclui '//', barra final), a home da conta e seus
    ancestrais. Não toca o disco além de resolver a home da conta."""
    if not isinstance(path, str) or not path or "\x00" in path or len(path) > MAX_PATH:
        raise PathGuardError("pasta autorizada deve ser caminho textual válido")
    if not path.startswith("/"):
        raise PathGuardError("pasta autorizada deve ser caminho absoluto")
    if path == "/":
        raise PathGuardError("a raiz do sistema não pode ser pasta autorizada")
    parts = path[1:].split("/")
    for p in parts:
        if p in ("", ".", ".."):
            raise PathGuardError("pasta autorizada não normalizada (//, '.', '..' ou barra final)")
        if len(p) > MAX_COMPONENT:
            raise PathGuardError("componente longo demais")
    for home in _protected_homes():
        if path == home or home.startswith(path + "/"):
            raise PathGuardError("pasta autorizada não pode ser a home da conta nem ancestral dela")
    return tuple(parts)


def open_root(path):
    """Abre a pasta autorizada e devolve um descritor. O caminho é percorrido componente a
    componente a partir de '/', com dir_fd e O_NOFOLLOW em cada passo: symlink em qualquer
    componente é recusado, sem depender de realpath. Não detecta bind mounts nem troca
    concorrente do caminho por quem tenha escrita nos diretórios ancestrais."""
    _require_platform()
    parts = check_authorized_path(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    try:
        cur = os.open("/", flags)
    except OSError as e:
        raise PathGuardError(f"não foi possível abrir '/': {e.strerror}") from None
    try:
        for name in parts:
            try:
                nxt = os.open(name, flags | os.O_NOFOLLOW, dir_fd=cur)
            except OSError as e:
                raise PathGuardError(f"pasta autorizada recusada ({e.strerror})") from None
            os.close(cur)
            cur = nxt
        return cur
    except BaseException:
        os.close(cur)
        raise


def _walk_dirs(root_fd, parts):
    """Abre os diretórios pais um a um; devolve fd do último (o chamador fecha)."""
    root_dev = os.fstat(root_fd).st_dev
    cur = os.dup(root_fd)
    try:
        for name in parts:
            try:
                nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=cur)
            except OSError as e:
                raise PathGuardError(f"diretório recusado ({e.strerror})") from None
            os.close(cur)
            cur = nxt
            if os.fstat(cur).st_dev != root_dev:
                raise PathGuardError("diretório em outro dispositivo")
        return cur
    except BaseException:
        os.close(cur)
        raise


def _check_regular(fd, root_fd):
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise PathGuardError("não é arquivo regular")
    if st.st_nlink != 1:
        raise PathGuardError("arquivo com mais de um link físico (hardlink)")
    if st.st_dev != os.fstat(root_fd).st_dev:
        raise PathGuardError("arquivo em outro dispositivo")
    return st


def read_bytes(root_fd, rel, max_bytes=DEFAULT_MAX_READ):
    parts = split_relpath(rel)
    dfd = _walk_dirs(root_fd, parts[:-1])
    try:
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=dfd)
        except OSError as e:
            raise PathGuardError(f"arquivo recusado ({e.strerror})") from None
        try:
            st = _check_regular(fd, root_fd)
            if st.st_size > max_bytes:
                raise PathGuardError("arquivo maior que o limite")
            data = os.read(fd, max_bytes + 1)
            if len(data) > max_bytes:
                raise PathGuardError("arquivo maior que o limite")
            return data
        finally:
            os.close(fd)
    finally:
        os.close(dfd)


def write_bytes(root_fd, rel, data, overwrite=False, max_bytes=DEFAULT_MAX_READ):
    """Cria arquivo (O_EXCL); com overwrite=True só substitui arquivo regular de link único.
    Diretórios pais precisam existir; nada é criado fora da pasta autorizada."""
    if type(overwrite) is not bool:
        raise PathGuardError("overwrite deve ser exatamente True ou False")
    if not isinstance(data, (bytes, bytearray)):
        raise PathGuardError("dados devem ser bytes")
    if len(data) > max_bytes:
        raise PathGuardError("dados maiores que o limite")
    parts = split_relpath(rel)
    dfd = _walk_dirs(root_fd, parts[:-1])
    try:
        base = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            if overwrite:
                try:
                    fd = os.open(parts[-1], base, dir_fd=dfd)
                except FileNotFoundError:
                    fd = os.open(parts[-1], base | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dfd)
            else:
                fd = os.open(parts[-1], base | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dfd)
        except OSError as e:
            raise PathGuardError(f"escrita recusada ({e.strerror})") from None
        try:
            _check_regular(fd, root_fd)  # confere antes de truncar/escrever
            os.ftruncate(fd, 0)
            view = memoryview(bytes(data))
            while view:
                n = os.write(fd, view)
                view = view[n:]
        finally:
            os.close(fd)
    finally:
        os.close(dfd)



class ListLimitExceeded(PathGuardError):
    """Listagem negada quando excede o limite de nomes autorizado."""


def list_dir(root_fd, rel=None, max_entries=100_000):
    """Lista nomes com limite ANTES de materializar uma pasta muito larga.

    scandir(fd) percorre em streaming; sorted() acontece só após cumprir o limite.
    O descritor entregue pelo chamador não é fechado aqui.
    """
    if type(max_entries) is not int or not 1 <= max_entries <= 100_000:
        raise PathGuardError("limite de listagem inválido")
    parts = split_relpath(rel) if rel is not None else ()
    dfd = _walk_dirs(root_fd, parts)
    try:
        names = []
        with os.scandir(dfd) as entries:
            for entry in entries:
                if len(names) >= max_entries:
                    raise ListLimitExceeded("limite de listagem excedido")
                names.append(entry.name)
        return sorted(names)
    finally:
        os.close(dfd)


def scan_tree(root_fd, max_entries=100_000, max_depth=64):
    """Inspeciona em streaming, sem seguir symlinks e com descritores limitados.

    No máximo max_entries objetos visitados e max_depth descritores de
    subdiretório abertos por caminho; sem listas completas de irmãos na memória.
    Retorna achados de symlinks, hardlinks, objetos especiais e outro device.
    Uma árvore limpa no instante do scan NÃO elimina TOCTOU ou bind mounts.
    """
    if type(max_entries) is not int or not 1 <= max_entries <= 100_000:
        raise PathGuardError("limite de varredura inválido")
    if type(max_depth) is not int or not 1 <= max_depth <= 64:
        raise PathGuardError("profundidade de varredura inválida")

    findings = []
    count = 0
    root_dev = os.fstat(root_fd).st_dev
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    def visit(dfd, prefix, depth):
        nonlocal count
        # scandir(fd) não materializa todos os nomes, ao contrário de os.listdir.
        with os.scandir(dfd) as entries:
            for entry in entries:
                count += 1
                if count > max_entries:
                    raise PathGuardError("árvore grande demais para varredura")
                rel = prefix + entry.name
                if len(rel) > MAX_PATH:
                    raise PathGuardError("caminho profundo demais para varredura")
                st = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(st.st_mode):
                    findings.append((rel, "symlink"))
                elif st.st_dev != root_dev:
                    findings.append((rel, "outro dispositivo"))
                elif stat.S_ISDIR(st.st_mode):
                    if depth >= max_depth:
                        raise PathGuardError("profundidade de varredura excedida")
                    try:
                        sub = os.open(entry.name, flags, dir_fd=dfd)
                    except OSError as e:
                        raise PathGuardError(f"varredura recusada ({e.strerror})") from None
                    try:
                        if os.fstat(sub).st_dev != root_dev:
                            findings.append((rel, "outro dispositivo"))
                        else:
                            visit(sub, rel + "/", depth + 1)
                    finally:
                        os.close(sub)
                elif not stat.S_ISREG(st.st_mode):
                    findings.append((rel, "tipo especial"))
                elif st.st_nlink != 1:
                    findings.append((rel, "hardlink"))

    visit(root_fd, "", 0)
    return sorted(findings)
