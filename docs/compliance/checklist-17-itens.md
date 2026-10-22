# Checklist de compliance — 17 itens

Origem: PDF-F3, seções 08 e 09 ("Checklist da imagem"), em [Plano_Ecossistema_Agentes_IA_2026.pdf](../references/Plano_Ecossistema_Agentes_IA_2026.pdf). Critérios resumidos fielmente; o PDF prevalece em caso de dúvida. Este checklist **organiza a verificação e não certifica conformidade jurídica** (ver [README](README.md)).

## Status e evidência
- Status permitidos: `não iniciado` · `conforme` · `parcial` · `não aplicável` (com justificativa curta; não equivale a "conforme").
- Evidência por projeto, em planilha ou JSON: item, status, URL ou componente analisado, prova (teste, captura, log), responsável, prioridade, data e fonte normativa. Modelo em [relatorio-por-projeto.md](relatorio-por-projeto.md).
- Natureza: **J** = principalmente jurídico-documental; **T** = exige teste técnico; **J+T** = ambos.

## Itens

| # | Tema | Critério verificável (PDF) | Natureza | Referência complementar |
|---|---|---|---|---|
| 01 | Política de privacidade | Explicar controladores, finalidades, bases legais, compartilhamentos, retenção, direitos e contato; refletir o sistema real. | J | LGPD; SEC-25 |
| 02 | Termos de serviço | Regras contratuais compreensíveis, funcionalidades, limitações, pagamento, cancelamento e responsabilidades. | J | CDC |
| 03 | Aviso de cookies | Mapear cookies; distinguir essenciais de opcionais; painel de preferências quando aplicável. | J+T | Guia de Cookies da ANPD |
| 04 | Política de reembolso | Explicar cancelamento e reembolso sem contrariar CDC/direito de arrependimento; diferenças por serviço. | J | CDC; Decreto 7.962/2013 |
| 05 | Formulários na LGPD | Finalidade e campos claros; base legal e transparência; não exigir aceite de marketing para contratar. | J+T | LGPD |
| 06 | Só dados necessários | Reduzir coleta e retenção; não pedir dados sem justificativa. | J+T | LGPD (minimização); SEC-25 |
| 07 | Scripts de tracking | Inventariar tags, vendors, consentimentos e bloqueios antes de ativar trackers não essenciais. | T | ANPD cookies; SEC-25 |
| 08 | Acessibilidade | Testar tecnologias assistivas e critérios WCAG relevantes; avaliar obrigações específicas. | T | WCAG |
| 09 | Alt nas imagens | Textos alternativos úteis quando a imagem transmite informação; decorativas podem ser ocultadas. | T | WCAG |
| 10 | Contraste corrigido | Medir contraste de texto e controles; priorizar WCAG 2.2 AA quando adequada. | T | WCAG 2.2 |
| 11 | Navegação por teclado | Foco visível, ordem lógica, modais acessíveis, ausência de bloqueios ao teclado. | T | WCAG |
| 12 | Sem avaliações falsas | Não inventar depoimentos, estrelas, volume de vendas ou avaliações. | J | CDC |
| 13 | Sem promessas falsas | Não afirmar segurança, funcionamento, resultados ou condições comerciais sem evidência. | J | CDC |
| 14 | Copyright das imagens | Licenças e autorizações de fotos, marcas, fontes e assets; identificar direitos de terceiros. | J | Direitos autorais e de imagem |
| 15 | Dados da empresa | Identificação e contatos necessários; informações claras de fornecedor e atendimento. | J | Decreto 7.962/2013; CDC |
| 16 | Conformidade LGPD | Mapeamento, bases legais, segurança, direitos do titular, contratos e resposta a incidentes. | J+T | LGPD; SEC-25, SEC-40 |
| 17 | Riscos jurídicos | Registro de riscos, revisão de especialistas, monitoramento normativo e correções documentadas. | J | — |

## Pontos adicionais por tipo de produto (PDF seção 09)
- **Eventos e mídia de convidados:** autorização e direitos de imagem, dados de convidados e crianças, exposição via link/QR, moderação de mídia, prazos de exclusão, visibilidade e termos para organizador versus convidado.
- **E-commerce:** fornecedor, oferta, preço, frete, estoque, checkout, arrependimento, atendimento, reembolso e registro de pedidos.
- **Apps com IA:** transparência da geração, proveniência/licenciamento de imagens e vozes, políticas de provedores, privacidade de prompts, decisões automatizadas e auditoria humana quando necessário.

## Base mínima aplicável a sites brasileiros (PDF seção 07)
LGPD e regulamentos da ANPD; CDC (relação de consumo); Decreto 7.962/2013 (e-commerce); Marco Civil da Internet; direitos autorais e de imagem; acessibilidade digital; regras contratuais e obrigações do segmento.
