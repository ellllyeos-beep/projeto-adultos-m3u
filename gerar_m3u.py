"""Gera playlist apenas de fontes com autorização registrada pelo mantenedor."""
import ipaddress
import json
import re
import socket
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, urljoin
import requests

TIMEOUT = (5, 15)
MAX_SOURCE = 4 * 1024 * 1024
BASE = Path(__file__).resolve().parent
ADULT_TERMS = re.compile(r'(?<!\w)(?:xxx|adultos?|adults?|18\+|porn\w*|sex|sexy|erotic\w*|erótic\w*|playboy|venus)(?!\w)', re.I)


def canonical_url(url):
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('URL inválida')
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError('URL HTTP(S) pública sem credenciais ou fragmento exigida')
    host = p.hostname.lower()
    port = p.port
    authority = f'[{host}]' if ':' in host else host
    if port and (p.scheme, port) not in (('http', 80), ('https', 443)):
        authority += f':{port}'
    return urlunsplit((p.scheme, authority, p.path or '/', p.query, ''))


def public_url(url, domains):
    url = canonical_url(url)
    p = urlsplit(url)
    if p.hostname not in domains:
        raise ValueError('Domínio fora da autorização')
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Destino não público')
    return url


def fetch(url, domains, limit):
    # Redirecionamentos são conferidos antes de cada conexão; nunca usa cookies/proxy do ambiente.
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(6):
            url = public_url(url, domains)
            with session.get(url, timeout=TIMEOUT, stream=True, allow_redirects=False,
                             headers={'User-Agent': 'Authorized-M3U/2.0'}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                response.raise_for_status()
                if response.status_code not in (200, 206):
                    raise ValueError('Resposta sem conteúdo de mídia')
                data = bytearray()
                for chunk in response.iter_content(4096):
                    data.extend(chunk[:limit - len(data)])
                    if len(data) >= limit:
                        break
                return bytes(data), response.headers.get('Content-Type', '').split(';')[0].lower()
    raise ValueError('Excesso de redirecionamentos')


def parse_m3u(text):
    pending = None
    for line in text.lstrip('\ufeff').splitlines():
        line = line.strip()
        if line.startswith('#EXTINF:'):
            # A vírgula dentro de atributos entre aspas não separa o nome.
            match = re.match(r'^#EXTINF:((?:[^",]|"[^"]*")*),(.*)$', line)
            pending = (match[2].strip(), dict(re.findall(r'([\w-]+)="([^"]*)"', match[1]))) if match else None
        elif line and not line.startswith('#'):
            if pending:
                yield (*pending, line)
            pending = None


def eh_adulto(nome, attrs):
    return bool(ADULT_TERMS.search(' '.join([nome, *(attrs.get(k, '') for k in ('group-title', 'tvg-name', 'tvg-id'))])))


def montar_extinf(nome, attrs):
    def clean(value):
        return ' '.join(str(value).replace('"', "'").split())
    attrs = {k: clean(v) for k, v in attrs.items() if re.fullmatch(r'[\w-]+', k)}
    attrs['tvg-name'] = attrs.get('tvg-name') or clean(nome)
    attrs['group-title'] = 'Adultos'
    return '#EXTINF:-1 ' + ' '.join(f'{k}="{v}"' for k, v in sorted(attrs.items()) if v) + ',' + clean(nome)


def stream_ativo(url, domains):
    data, mime = fetch(url, domains, 8192)
    prefix = data.lstrip(b'\xef\xbb\xbf\r\n\t ')
    if prefix.startswith(b'#EXTM3U'):
        return b'#EXT-X-' in prefix
    if prefix.startswith(b'<') or mime in ('text/html', 'application/json'):
        return False
    return bool(data) and (mime.startswith(('video/', 'audio/')) or (len(data) > 188 and data[0] == 0x47 and data[188] == 0x47))


def authorized(source):
    auth = source.get('autorizacao', {})
    return (auth.get('confirmada') is True and bool(auth.get('evidencia', '').strip())
            and bool(source.get('dominios_stream')) and bool(source.get('dominios_fonte')))


def generate(sources):
    output = ['#EXTM3U']
    seen = set()
    status = dict(fontes_configuradas=len(sources), fontes_sem_autorizacao=0,
                  entradas_m3u_lidas=0, entradas_identificadas_como_adultas=0,
                  duplicados=0, urls_rejeitadas=0, removidos_por_falha_no_teste=0,
                  canais_ativos=0, erros_de_fontes=[])
    for source in sources:
        if not authorized(source):
            status['fontes_sem_autorizacao'] += 1
            continue
        try:
            data, _ = fetch(source['url'], source['dominios_fonte'], MAX_SOURCE + 1)
            if len(data) > MAX_SOURCE or not data.decode('utf-8-sig').lstrip().startswith('#EXTM3U'):
                raise ValueError('Fonte não é uma playlist M3U válida ou excede limite')
            entries = list(parse_m3u(data.decode('utf-8-sig')))
        except (requests.RequestException, ValueError, OSError, KeyError) as exc:
            status['erros_de_fontes'].append({'fonte': source.get('nome', ''), 'erro': type(exc).__name__})
            continue
        for name, attrs, url in entries:
            status['entradas_m3u_lidas'] += 1
            if not eh_adulto(name, attrs):
                continue
            status['entradas_identificadas_como_adultas'] += 1
            try:
                key = canonical_url(url)
                if urlsplit(key).hostname not in source['dominios_stream']:
                    raise ValueError('Domínio não autorizado')
            except ValueError:
                status['urls_rejeitadas'] += 1
                continue
            if key in seen:
                status['duplicados'] += 1
                continue
            seen.add(key)
            try:
                active = stream_ativo(key, source['dominios_stream'])
            except (requests.RequestException, ValueError, OSError):
                active = False
            if not active:
                status['removidos_por_falha_no_teste'] += 1
                continue
            output.extend((montar_extinf(name, attrs), key))
            status['canais_ativos'] += 1
    return '\n'.join(output) + '\n', status


def main():
    sources = json.loads((BASE / 'fontes.json').read_text(encoding='utf-8'))['fontes']
    playlist, status = generate(sources)
    # Falha de fonte não apaga a última playlist publicada.
    if status['erros_de_fontes']:
        raise SystemExit('Falha ao consultar fontes; arquivos anteriores preservados')
    for name, text in [('adultos.m3u', playlist), ('status.json', json.dumps(status, ensure_ascii=False, indent=2) + '\n')]:
        target = BASE / name
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_text(text, encoding='utf-8', newline='\n')
        temporary.replace(target)
    print(json.dumps(status, ensure_ascii=False))


if __name__ == '__main__':
    main()
