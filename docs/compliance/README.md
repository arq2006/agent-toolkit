# Compliance jurídico e auditoria técnica de segurança

Status: **estrutura e modelos** (F0.2, origem PDF-F3, destino GH-F2). Não há skill, script nem automação nesta fase. Decisão: [ADR-008](../adr/ADR-008-compliance-juridico-separado-do-tecnico.md).

> Aviso: estes documentos são checklists de organização e recomendação com fontes. **Não são aconselhamento jurídico, certificação LGPD nem pentest.** Políticas, contratos e decisões de alto impacto exigem revisão profissional.

## Duas trilhas independentes

| | Auditoria jurídica (compliance) | Auditoria técnica de segurança |
|---|---|---|
| Pergunta | O produto cumpre obrigações legais e comerciais aplicáveis? | O sistema resiste a abusos e falhas exploráveis? |
| Referência | [Checklist de 17 itens](checklist-17-itens.md), LGPD/ANPD, CDC, Decreto 7.962/2013, Marco Civil | [Roadmap de segurança geral v3](../security/Roadmap_Seguranca_Geral_v3.md) (SEC-00 a SEC-42), OWASP ASVS |
| Saída | [Relatório de compliance por projeto](relatorio-por-projeto.md) com [mapa de dados](mapa-de-dados.md) | Achados SEC-FINDING com evidência e severidade |
| Executor | Agente jurídico-documental (futuro `legal-web-check`) + revisão de profissional | Agente auditor técnico read-only |
| Limite | Recomenda e cita fontes; não interpreta nem certifica | Não comprova conformidade jurídica (ver SEC-25) |

Elas se **complementam e se cruzam** (privacidade, retenção, logs, terceiros), mas nenhuma substitui a outra: passar em scanners não é estar "100% LGPD", e ter política de privacidade não é estar em conformidade. Cada relatório declara qual trilha foi executada. O roadmap de segurança é referência **complementar**: SEC-25 (privacidade/PII/LGPD), SEC-00 (inventário) e SEC-42 (agentes/IA) alimentam o mapa de dados e a ficha do projeto.

## Fluxo previsto por projeto (GH-F2)
1. Identificar produto, jurisdição e fluxos de dados (ficha do projeto, como no roadmap de segurança).
2. Preencher o [mapa de dados](mapa-de-dados.md) **antes** de gerar ou revisar qualquer política.
3. Avaliar os 17 itens com evidência verificável; itens inaplicáveis levam justificativa.
4. Consultar fontes oficiais com link e data (Planalto, ANPD, portais oficiais). O acervo `ctresb/leis` é auxiliar de consulta, **não** fonte oficial (o Diário Oficial e as fontes originais prevalecem).
5. Emitir o [relatório](relatorio-por-projeto.md) com achados, severidade, evidência e texto normativo, separando recomendação técnica de interpretação jurídica.
6. Encaminhar a revisão profissional (políticas, contratos, riscos altos) e registrar monitoramento normativo.

## Onde ficam os resultados
Relatórios, mapas de dados preenchidos e evidências ficam **no repositório ou ambiente do projeto auditado**, nunca neste repositório público. Aqui ficam apenas modelos e exemplos fictícios.

## Fontes oficiais iniciais
[LGPD](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm) · [ANPD](https://www.gov.br/anpd/pt-br) · [CDC](https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm) · [Decreto 7.962/2013](https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/decreto/d7962.htm) · [Marco Civil da Internet](https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm). Verificar vigência na data da consulta.
