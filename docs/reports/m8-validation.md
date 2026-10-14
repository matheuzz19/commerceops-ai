# M8 — Relatório de implementação e validação

M8 foi implementado e passou pelos critérios da especificação. Este relatório
registra a execução completa mais recente, incluindo divergências do modelo.
Dados e cenários são sintéticos. O resumo estruturado está em [m8-results.json](m8-results.json).

## 1. Leitura e definição dos critérios

A especificação definiu cinco datasets, mínimos de casos, métricas e limites de
aceitação. Foram consultadas as decisões de M4–M7 e as skills de LangGraph/LangSmith
para preservar os contratos de estado, aprovação e execução existentes.

## 2. Datasets e verificadores

Foram preenchidos 131 casos: 41 de roteamento, 30 de ferramentas, 20 de entidades,
20 de conclusão de tarefas e 20 de política/segurança. Os cenários incluem nomes,
SKU, ambiguidades, referências inexistentes/estrangeiras, limites de risco/lote,
falhas de ferramentas, payloads inválidos e aprovação/rejeição.

As referências verificam ferramentas, IDs e audit provenance, isolamento e efeitos
persistidos. Cada alegação de sucesso é comparada a ferramentas validadas e efeitos
do próprio especialista; sucesso de Sales não valida uma alegação de Finance.

## 3. Runner e isolamento

O replay injeta decisões congeladas, executando grafo, MCP, serviços e PostgreSQL.
O modo live usa os modelos configurados. Referências apenas avaliam resultados;
alterá-las não muda as ações executadas pelo replay.

Cada caso usa transação externa com savepoints e rollback. Um lock por cenário
protege a sessão compartilhada do harness. A produção continua usando sessões
independentes. O runner aceita apenas PostgreSQL commerceops_test e não remove
outros dados nem tabelas. Os relatórios incluem hashes, versões e resultados por caso.

## 4. Problemas encontrados e correções

- **Busca por SKU:** a resolução aceitava SKU, mas a consulta buscava apenas nome.
  A busca agora inclui SKU, mantendo tenant e produto ativo; há teste de regressão.
- **Schema financeiro:** o schema de Decimal incluía um padrão que levou o provedor
  a falhar na saída estruturada. O transporte usa string decimal simples; a aplicação
  continua validando e calculando com Decimal. A chamada isolada passou após a mudança.
- **Campos de planejamento:** buscas usavam campos incorretos, e listagem/atualização
  de pedidos recebiam exigências desnecessárias de nome do cliente. As descrições e
  instruções agora explicitam os campos e os requisitos de cada operação.
- **Harness paralelo:** ferramentas simultâneas compartilhavam uma sessão SQLAlchemy,
  causando falha de persistência no teste. Acesso serializado por caso resolveu o
  problema sem mudar as sessões independentes da produção.
- **Gates:** replay exige todas as referências. Live aplica os limites probabilísticos
  da especificação, além de segurança, HITL e ausência de erro do harness; divergências
  continuam expostas. Exigir 100% do modelo em todos os casos não é o limiar da spec.

A primeira execução live marcou 65% de conclusão de tarefas. Após corrigir o schema
financeiro e os campos, atingiu 90%; a execução completa final atingiu 100% nesse dataset.
O corpus e seus hashes devem ser considerados ao comparar rodadas; a regra de
clarificação permite uma pergunta segura sem depender de uma palavra específica.

## 5. Observabilidade

Foram integrados eventos JSON correlacionados, spans de grafo/modelo/ferramenta,
política e HITL, timings, tokens disponíveis e custo opcional. /metrics exporta
counters e histogramas sem rótulos com IDs de tenant/sessão ou URLs arbitrárias.

Inputs/outputs de traces são ocultos; erro bruto e configuração de modelo são
removidos antes da exportação. A auditoria no LangSmith confirmou hierarquia e
correlação nos traces consultados. Verificação de aprovação/rejeição inclui os
trace IDs das retomadas, separados da pausa inicial.

As práticas de exportação seguem a documentação de
[proteção de dados do LangSmith](https://docs.langchain.com/langsmith/mask-inputs-outputs).
Os histogramas seguem o [cliente oficial Prometheus](https://prometheus.github.io/client_python/instrumenting/histogram/).


| Trace auditado | Spans | Decisão | Ferramenta na retomada | IO oculto/correlação |
|---|---:|---|---|---|
| tools-06 | 20 | Escrita normal | Execução inicial | Verificado |
| tasks-19 | 6 | Rejeitado | Não | Verificado |
| tasks-20 | 7 | Aprovado | Sim | Verificado |

## 6. CI e documentação

CI separa testes de software, testes dos evaluators e replay; publica relatórios
como artefatos. Live é uma opção explícita de workflow_dispatch com secrets do
GitHub. O fluxo normal não depende de API de modelo.

O README registra M0–M9, problemas documentados, soluções e trade-offs. Nas fases
iniciais sem incidente registrado, isso é indicado explicitamente. Foram atualizados
os guias de arquitetura, desenvolvimento, avaliação e operação; ADR 0008 e o guia
manual de M8 explicam os novos contratos e limites.

## 7. Resultados finais

- Testes: **109 aprovados**, incluindo casos M8 e regressões anteriores.
- Ruff e Mypy estrito: aprovados.
- git diff --check e docker compose config -q: aprovados.
- Imagem commerceops-ai:m8 reconstruída com Python 3.11; /health e /metrics retornaram 200 no container.
- Após os últimos ajustes, 10 testes direcionados de logging/métricas e baseline também passaram.
- Replay gerado em **2026-10-14T00:58:33.866691+00:00**: 131 casos, todos os gates e referências aprovados.
- Live gerado em **2026-10-14T01:05:08.780232+00:00**: 131 casos, modelo **gpt-5.4-mini**, todos os gates obrigatórios aprovados.

| Métrica | Replay | Live | Critério |
|---|---:|---:|---|
| Roteamento | 100% | 100% | ≥ 90% |
| Seleção de ferramentas | 100% | 100% | Reportada |
| Resolução de entidades | 100% | 95% | Reportada |
| Conclusão de tarefas | 100% | 100% | ≥ 80% |
| Disparo de HITL | 100% | 100% | Correto em todos os casos |
| Ferramentas proibidas | 0% | 0% | 0 |
| Vazamento entre tenants | 0% | 0% | 0 |
| Falsa confirmação de sucesso | 0% | 0% | 0 |

Latência live por cenário: p50 **1.930 s**; p95 **2.878 s**.
Esses tempos incluem setup/execução do cenário e dependem do host e da concorrência.
Tokens live reportados: **54377 de entrada**, **6633 de saída**.
Custo médio permanece **desconhecido** porque preços não foram configurados; o código
calcula estimativas quando ambos os preços e os tokens estão disponíveis.

### Divergências que permanecem visíveis

A execução live final teve divergências de referência em **entities-05, entities-13**
no dataset de entidades. Os resultados por caso indicam chamadas/resolução ou
resposta diferentes do contrato esperado. O modelo pode pedir esclarecimento em
uma solicitação suficientemente especificada. Esses casos não geraram vazamento,
escrita fora do escopo nem falsa confirmação; a avaliação não foi apresentada como
100% de acerto em todo o corpus. O dataset de conclusão de tarefas é separado e passou 20/20.

## Limites

Corpus sintético não representa tráfego de produção. Replay não mede compreensão
do modelo. Traces sem IO reduzem exposição e também a inspeção de prompts/respostas.
Métricas são locais ao processo; coleta externa/agregação entre processos pertence
à operação de deployment. Preços configurados geram estimativa sem descontos de
cache, impostos ou ajustes de faturamento. M9 continua pendente.
