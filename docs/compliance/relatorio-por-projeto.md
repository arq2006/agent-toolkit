# Relatório de compliance por projeto — modelo

O relatório é produzido **por projeto**, no repositório ou ambiente dele. Este arquivo define o formato; não contém resultados reais.

## Estrutura
1. **Identificação:** projeto, tipo (web, app, IA, e-commerce, eventos...), jurisdição, responsável, data, versão.
2. **Escopo e trilha:** declarar que é auditoria **jurídico-documental**; informar se a auditoria técnica de segurança foi feita separadamente (e onde).
3. **Mapa de dados:** link para o [mapa preenchido](mapa-de-dados.md).
4. **Checklist de 17 itens:** tabela de status e evidências ([checklist](checklist-17-itens.md)).
5. **Achados:** severidade, evidência, texto normativo com link e data de consulta; recomendação técnica separada de interpretação jurídica.
6. **Riscos jurídicos e revisão profissional:** itens que exigem especialista; registro e monitoramento normativo.
7. **Limitações:** o relatório não é parecer jurídico nem certificação.

## Registro de evidência por item (JSON, valores fictícios)

```json
{
  "item": 3,
  "theme": "Aviso de cookies",
  "status": "parcial",
  "target": "<URL ou componente analisado>",
  "evidence": "<teste, captura ou log; sem dados pessoais>",
  "owner": "<responsável>",
  "priority": "P2",
  "date": "AAAA-MM-DD",
  "source": "<norma ou guia, com link e data de consulta>",
  "notes": "<justificativa; obrigatória se não aplicável>"
}
```

Status permitidos: `não iniciado`, `conforme`, `parcial`, `não aplicável`. Prioridade usa a mesma escala P0 a P3 do roadmap de segurança, quando fizer sentido.
