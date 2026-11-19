import unittest
from unittest.mock import patch, MagicMock
import gerar_m3u as g

SOURCE = {'nome': 'Fixture', 'url': 'https://source.example/list',
          'dominios_fonte': ['source.example'], 'dominios_stream': ['media.example'],
          'autorizacao': {'confirmada': True, 'evidencia': 'Permissão do titular, fixture de teste'}}

class GeneratorTests(unittest.TestCase):
    def test_case_sensitive_path_and_query(self):
        self.assertNotEqual(g.canonical_url('https://MEDIA.example/A?Key=X'), g.canonical_url('https://media.example/a?Key=x'))
        self.assertEqual(g.canonical_url('https://MEDIA.example:443/A'), 'https://media.example/A')

    def test_bad_urls(self):
        for url in ['file:///a', 'https://user:pass@media.example/a', 'https://media.example/a\n', 'https://media.example/a#x', 'https://media.example:bad/a']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                g.canonical_url(url)

    def test_parser_comments_bom_and_quoted_comma(self):
        text = '\ufeff#EXTM3U\n#EXTINF:-1 tvg-name="Adult, HD",Adult HD\n# comment\nhttps://media.example/A\n'
        self.assertEqual(list(g.parse_m3u(text)), [('Adult HD', {'tvg-name': 'Adult, HD'}, 'https://media.example/A')])

    def test_orphan_entry(self):
        self.assertEqual(list(g.parse_m3u('#EXTINF:-1,Broken\n#EXTINF:-1,Adult\nhttps://media.example/a')), [('Adult', {}, 'https://media.example/a')])

    def test_category_false_positives(self):
        self.assertFalse(g.eh_adulto('Hot news Sussex', {}))
        self.assertTrue(g.eh_adulto('Canal', {'group-title': 'Adultos'}))

    def test_metadata_sanitized(self):
        line = g.montar_extinf('Adult\n#evil', {'custom': 'kept', 'tvg-name': 'a"b'})
        self.assertNotIn('\n', line)
        self.assertIn('custom="kept"', line)
        self.assertIn('group-title="Adultos"', line)

    @patch.object(g, 'fetch')
    def test_unapproved_never_fetched(self, fetch):
        output, status = g.generate([{'url': 'https://source.example'}])
        fetch.assert_not_called()
        self.assertEqual(output, '#EXTM3U\n')
        self.assertEqual(status['fontes_sem_autorizacao'], 1)

    @patch.object(g, 'stream_ativo', return_value=False)
    @patch.object(g, 'fetch', return_value=(b'#EXTM3U\n#EXTINF:-1,Adult\nhttps://media.example/A\n#EXTINF:-1,Adult\nhttps://MEDIA.example:443/A\n', 'text/plain'))
    def test_failed_duplicate_tested_once(self, fetch, probe):
        _, status = g.generate([SOURCE])
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(status['duplicados'], 1)
        self.assertEqual(status['removidos_por_falha_no_teste'], 1)

    @patch.object(g, 'fetch')
    def test_probe_content(self, fetch):
        for data, mime, expected in [(b'<html>login</html>', 'text/html', False), (b'', 'video/mp2t', False), (b'#EXTM3U\n#EXT-X-TARGETDURATION:6', 'text/plain', True), (b'#EXTM3U\nhttps://example.com', 'text/plain', False)]:
            fetch.return_value = data, mime
            self.assertEqual(g.stream_ativo('https://media.example/a', ['media.example']), expected)

    @patch.object(g.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))])
    def test_private_address_blocked(self, dns):
        with self.assertRaises(ValueError):
            g.public_url('https://media.example/a', ['media.example'])

    @patch.object(g, 'public_url')
    @patch.object(g.requests, 'Session')
    def test_redirect_checked_before_connection(self, session, check):
        check.side_effect = ['https://media.example/a', ValueError('blocked')]
        client = session.return_value.__enter__.return_value
        response = client.get.return_value.__enter__.return_value
        response.status_code = 302
        response.headers = {'Location': 'http://127.0.0.1/internal'}
        with self.assertRaises(ValueError):
            g.fetch('https://media.example/a', ['media.example'], 8192)
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(check.call_args.args[0], 'http://127.0.0.1/internal')

    @patch.object(g, 'fetch', side_effect=ValueError('invalid source'))
    def test_source_failure_recorded(self, fetch):
        _, status = g.generate([SOURCE])
        self.assertEqual(len(status['erros_de_fontes']), 1)

    @patch.object(g, 'stream_ativo', return_value=True)
    @patch.object(g, 'fetch', return_value=(b'#EXTM3U\n#EXTINF:-1,Adult\nhttps://other.example/A\n#EXTINF:-1,Adult\nhttps://media.example/A\n', 'text/plain'))
    def test_only_authorized_domain_published(self, fetch, probe):
        output, status = g.generate([SOURCE])
        self.assertNotIn('other.example', output)
        self.assertEqual(status['canais_ativos'], 1)
        self.assertEqual(status['urls_rejeitadas'], 1)

if __name__ == '__main__':
    unittest.main()
