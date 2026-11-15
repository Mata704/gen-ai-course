# Registo de progresso

Este documento acompanha, por marcos, o trabalho efetivamente concluído no
projeto. Cada entrada deve registar a data, o que foi alterado e como foi
validado; planos futuros devem ser identificados como pendentes, não como
funcionalidades existentes.

## 2026-11-15 — Fundação do projeto e simulador inicial

### Feito

- Criada a pasta independente `projects/agentic-data-quality/`, com
  configuração própria de Python e UV (`pyproject.toml`, `uv.lock` e ambiente
  virtual local).
- Criado o pacote `data_quality_agent` e um CLI para executar cenários e
  imprimir resultados estruturados em JSON.
- Implementado um simulador determinístico de pipelines com dados sintéticos
  de encomendas. A seed do cenário torna reproduzível a ordenação dos registos.
- Implementadas verificações de schema, valores obrigatórios, unicidade,
  intervalos numéricos, valores permitidos, integridade referencial, volume
  mínimo e frescura dos dados.
- Criados cenários para execução saudável, múltiplos problemas de qualidade,
  alteração de schema, atraso/baixo volume e indisponibilidade da fonte.
- Separados os estados da execução do pipeline e das verificações de Data
  Quality: uma pipeline pode terminar com sucesso e ainda assim produzir
  achados de qualidade; uma fonte indisponível deixa as verificações como não
  executadas.
- Documentadas instalação, execução e testes no `README.md`.

### Validação

- `uv sync --extra dev` — concluído.
- `uv run pytest` — 5 testes passaram.
- `uv lock --check` — concluído.
- `uv build` — wheel e source distribution construídos; os ficheiros JSON de
  definições, datasets e cenários foram confirmados no wheel.
- Execuções CLI dos cenários saudável e com problemas de qualidade — resultados
  estruturados e esperados.

### Ainda por fazer

Agentes, workflows, persistência SQLite, ferramentas MCP e interface Streamlit
ainda não foram implementados. A próxima etapa prevista é evoluir o simulador
e o harness determinístico antes de integrar agentes.

## 2026-11-15 — Guia de funcionamento

- Criado o guia [como vai funcionar o projeto](como-funciona.md), com um
  esquema, um exemplo e as fases previstas, distinguindo o que já existe do
  que ainda será desenvolvido.
- Adicionada uma ligação ao guia no `README.md`. Esta alteração é apenas
  documental; não modifica o comportamento do simulador.

## 2026-11-15 — Pipeline de ingestão e ponto de intervenção dos agentes

### Feito

- Evoluído o simulador para uma pipeline com etapas explícitas: ingestão JSON,
  transformação, Data Quality determinístico, intervenção dos agentes,
  revalidação e carregamento.
- Adicionados `--input` para receber um lote local e `--database` para escolher
  o destino SQLite. Os dados sintéticos e cenários existentes continuam
  disponíveis.
- Implementada uma transformação simples que normaliza `status`, sem alterar
  o ficheiro de entrada. O resultado distingue dados recebidos, transformados
  e carregados.
- Extraídas as regras para um bloco de Data Quality separado. A verificação
  de schema também deteta uma coluna em falta num único registo.
- Alterado intencionalmente o comportamento anterior: problemas de qualidade
  deixam agora a pipeline `blocked`, em vez de `succeeded`.
- Criado um incidente estruturado, com referência à execução e às regras que
  falharam. A etapa de intervenção fica `pending`, sem fingir executar agentes.
- Implementado carregamento transacional dos lotes aprovados em SQLite,
  com leitura de confirmação e rollback se os dados não corresponderem.
  Lotes bloqueados não são carregados e não alteram saídas anteriores.
- Mantidas explícitas as falhas de ingestão e de destino, sem apresentar
  recuperação ou carregamento como concluídos quando não foram confirmados.
- Atualizados o guia simples, a arquitetura e as instruções de execução para
  distinguir o fluxo atual da futura atuação dos agentes.

### Validação

- `uv run --locked --extra dev pytest -q` — 20 testes passaram, incluindo
  transformação, bloqueio, entrada inválida, persistência, falha de destino e
  rollback após divergência na leitura.
- `uv lock --check` e `uv build` — concluídos; módulos e dados incluídos no wheel.
- Execuções reais do CLI com lote local e cenário de qualidade — confirmado
  que só o lote aprovado ficou gravado em SQLite e que o outro ficou bloqueado
  com intervenção pendente.

### Próxima fase

Integrar os agentes no ponto pendente para investigar problemas de ingestão
e solicitar ações controladas, como repetir uma leitura ou reprocessar um
lote corrigido. Depois de uma ação, repetir as etapas afetadas e o bloco de
Data Quality antes de permitir o carregamento.

**Ainda não implementados:** agentes, ações corretivas, revalidação após ações,
retoma e persistência do contexto dos incidentes. Atualmente, SQLite guarda
apenas os dados aprovados; o contexto do lote bloqueado é devolvido em JSON.

## 2026-11-15 — Modelo multi-agent com sub-agents, tools, MCP e hooks

- Corrigido o desenho dos agentes no [guia](como-funciona.md) e na
  [proposta](proposta-arquitetura.md): o orquestrador deixa de aparecer como
  um passo de uma cadeia sequencial e passa a gerir dinamicamente vários
  sub-agents (qualidade, diagnóstico, remediação e revisor), em paralelo
  quando faz sentido. Os sub-agents só comunicam com o orquestrador.
- Acrescentada aos esquemas a camada de tools: tools Python locais, servidor
  MCP local e hooks antes/depois de cada tool e no fim da execução, com a
  lista de tools prevista por sub-agent.
- Alteração apenas documental; o código não mudou.

## Próximos registos

Adicionar uma nova secção datada quando um marco for concluído. Atualizar este
ficheiro e os comandos relevantes no `README.md` nessa altura.
