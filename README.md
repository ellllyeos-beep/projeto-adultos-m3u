# Gerador M3U de streams públicos autorizados

O gerador só consulta fontes com autorização registrada. Uma URL pública ou resposta HTTP 200 não comprova direitos de distribuição. As fontes anteriores foram desativadas porque não traziam evidência de autorização; nenhuma fonte nova foi presumida autorizada.

## Configuração

Em `fontes.json`, adicione objetos à lista `fontes` com os campos:

```json
{
  "nome": "Fornecedor autorizado",
  "url": "https://provider.example/playlist.m3u",
  "dominios_fonte": ["provider.example"],
  "dominios_stream": ["media.provider.example"],
  "autorizacao": {
    "confirmada": true,
    "evidencia": "URL dos termos ou referência da permissão do titular para estes streams"
  }
}
```

O mantenedor deve verificar a evidência e seu alcance antes de confirmar. A declaração é um registro manual, não uma verificação jurídica automática. Domínios são exatos, em minúsculas; inclua explicitamente CDNs e destinos de redirecionamento permitidos. Não use URLs com credenciais ou tokens privados em um repositório público.

## Execução e testes

Python 3.12:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python gerar_m3u.py
```

Os arquivos são resolvidos em relação ao script. Configuração vazia produz somente `#EXTM3U`. Falhas ao consultar fontes encerram a execução sem substituir os arquivos anteriores. Falhas individuais de streams removem somente esses streams. Cada arquivo é substituído atomicamente; os dois arquivos não constituem uma transação conjunta.

A validação usa GET com leitura limitada e timeout, rejeita HTML e exige assinatura HLS ou conteúdo de mídia. É uma verificação pontual, não garantia de reprodução completa ou disponibilidade futura. Não verifica segmentos HLS nem DRM. DNS público é conferido antes das conexões, mas isso não fornece isolamento contra DNS rebinding; use apenas fornecedores confiáveis.

A deduplicação normaliza esquema, hostname e portas padrão, preservando maiúsculas, caminho e query. Cada URL é testada uma vez por execução, mesmo quando falha. Contadores distinguem duplicados, URLs rejeitadas e falhas de mídia. Metadados são preservados e higienizados.

## GitHub Actions

`testes.yml` verifica pushes e pull requests sem escrever no repositório. `atualizar.yml` testa antes de gerar, evita execuções concorrentes e publica somente os dois arquivos gerados na main. Agenda: `17 */6 * * *`, às 00:17, 06:17, 12:17 e 18:17 UTC (20:17 do dia anterior, 02:17, 08:17 e 14:17 em Cuiabá).

O GitHub executa schedules apenas quando o workflow está na branch padrão; pode haver atrasos. Em forks, pode ser necessário habilitar Actions/agendamento manualmente. Esta proposta permanece em branch separada, sem integração; portanto a agenda nova ainda não está ativa. O workflow antigo da main não é alterado por esta branch.

Original preservado em `backup/original-21647b3`, commit `21647b3`. Alterações em `fix/authorized-stream-validation`.
