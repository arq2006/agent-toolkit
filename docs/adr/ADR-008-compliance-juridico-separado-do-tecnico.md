# ADR-008 — Compliance jurídico separado da auditoria técnica

**Status:** aceita (F0.2, 22/10/2026)

## Contexto
O PDF-F3 prevê checklist de 17 itens, mapa de dados, fontes oficiais e relatório por projeto, e afirma que compliance e cibersegurança se complementam sem serem equivalentes. O roadmap técnico original não citava esses entregáveis (lacuna registrada na ADR-006). O roadmap de segurança geral (SEC-25) também afirma que a análise técnica não comprova conformidade jurídica.

## Decisão
1. Os 17 itens, o mapa de dados e o relatório por projeto são incorporados em [docs/compliance/](../compliance/README.md) e atribuídos à GH-F2.
2. Duas trilhas independentes: **auditoria jurídica** (checklist, mapa, fontes oficiais, revisão profissional) e **auditoria técnica de segurança** (roadmap SEC-00 a SEC-42, OWASP). Relatórios declaram qual trilha foi executada.
3. O roadmap de segurança geral é referência complementar (SEC-25, SEC-00, SEC-42), sem alterar o documento importado.
4. A saída do toolkit é recomendação com fontes e evidência, nunca parecer jurídico ou certificação; revisão profissional é exigida para políticas, contratos e alto impacto.
5. Resultados reais ficam nos repositórios dos projetos; aqui só modelos e exemplos fictícios.

## Consequências
- Nenhuma funcionalidade do PDF-F3 fica sem destino; implementação (skill `legal-web-check`, validadores) só na GH-F2, após aprovação.
- Os itens de acessibilidade (08 a 11) são técnicos, mas ficam no checklist jurídico por constarem do PDF; a natureza J/T está marcada.
- Pendência: definir o formato de arquivo final (YAML/JSON) e os testes de contrato na GH-F2.
