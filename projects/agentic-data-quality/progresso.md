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

## 2026-11-15 — Interface Streamlit ao estilo GitHub Actions

### Feito

- O motor passou a publicar eventos de progresso (`stage_started`,
  `stage_finished` e `log`) através de `run(..., on_event=...)`, sempre pela
  ordem das etapas. Os eventos também ficam em `events` no resultado. A lógica
  e os estados da pipeline não mudaram.
- Erros inesperados na leitura da entrada fecham a etapa em curso como
  falhada antes de propagar o erro.
- Criado o módulo `src/data_quality_agent/ui/` e o comando
  `data-quality-ui`, que só escuta em `localhost`:
  - barra lateral para escolher o cenário, o destino SQLite e uma pausa visual
    por etapa, e iniciar a execução;
  - grafo das seis etapas e logs por etapa, atualizados ao vivo, com a etapa
    em curso destacada;
  - lista das execuções da sessão, métricas, regras falhadas, incidente e
    dados do lote.
- A lógica de apresentação (`view_model.py`) está separada do Streamlit e é
  testada diretamente.
- Adicionada a dependência `streamlit`.

### Validação

- `uv run --locked --extra dev pytest -q` — 26 testes passaram, incluindo os
  eventos ao vivo e a sua ordem, os logs das regras falhadas, o fecho da
  execução com erro de entrada, o estado intermédio do grafo e um teste da
  página com `streamlit.testing` (duas execuções e mudança de seleção).
- Servidor arrancado e verificado no browser: acompanhamento ao vivo, grafo e
  lista de execuções. Um erro de seleção da execução mais recente, apanhado
  pelo teste da página, foi corrigido.

### Ainda por fazer

Os passos dos agentes e das tools ainda não aparecem, porque ainda não
existem. O histórico passou a SQLite no marco seguinte.

## 2026-11-15 — Persistência SQLite, tools, hooks e servidor MCP

### Feito

- **SQLite como fonte de verdade** (`persistence/`): migrações versionadas e
  repositórios. Cada execução guarda a definição da pipeline (versionada por
  hash), estado, etapas, eventos ao vivo, lote recebido e transformado,
  resultado das regras, incidente e, só quando tudo passou, o lote carregado.
  Uma execução com erro de entrada fica como `failed`. Destinos antigos com
  `pipeline_output` são aproveitados.
- `PipelineService` junta o simulador e a persistência; o CLI e a interface
  usam-no. O histórico da interface passou a vir de SQLite.
- **Tools de leitura** para os sub-agents, com resultados pequenos e
  referências de evidência. Nunca revelam o cenário nem os logs que só
  descrevem a simulação (marcados com `simulation_only` e mostrados na
  interface com `[simulador]`).
- **Runbooks** versionados em `src/data_quality_agent/runbooks/`, associados
  aos tipos de regra, e a tool `find_runbook`.
- **Catálogo por agente e `ToolGateway`** com hooks antes da tool (allowlist e
  limite de chamadas) e depois (limite de tamanho e marca de conteúdo não
  confiável), e auditoria de todas as chamadas em `tool_calls`.
- **Servidor MCP único** (`data-quality-mcp --agent <nome>`, stdio), que só
  anuncia as tools do agente e usa o mesmo gateway.
- `context.incident_brief`: resumo inicial curto para o orquestrador.
- Adicionada a dependência `fastmcp-slim[server]`.

### Validação

- `uv run --locked --extra dev pytest -q` — 35 testes passaram, incluindo a
  reconstrução exata de execuções a partir de SQLite, a migração de um destino
  antigo, a ausência do cenário nos resultados das tools, os bloqueios e a
  auditoria do gateway, as tools por agente via MCP e o histórico da interface
  numa nova sessão.
- Servidor MCP testado por stdio real com o agente `quality`.
- `uv lock --check` e `uv build` confirmados; os runbooks são incluídos no
  pacote.

### Ainda por fazer

Agentes PydanticAI, ações e aprovações, hook de fim de execução, revalidação,
retoma, memória e bloqueio por hash das descrições das tools.

## 2026-11-15 — Duas bases de dados: local e plataforma da origem via MCP

### Feito

- O servidor MCP passou a representar a **plataforma da equipa que produz as
  encomendas**, um sistema que não controlamos. Tem o seu próprio SQLite
  (`mcp/data/orders_platform.sqlite3`), já incluído no projeto e gerado a
  partir de `platform.sql`, que o servidor abre só para leitura (`mode=ro`).
  Contém o contrato do dataset, alterações de esquema anunciadas, estado e
  janelas de manutenção da origem, incidentes da equipa de origem e o cadastro
  de clientes. Os dados dão pistas para os cenários sem revelar a resposta, e
  um incidente inclui um comentário a pedir para ignorar as verificações, para
  testar os guardrails.
- 5 tools MCP: `get_dataset_contract`, `list_schema_changes`,
  `get_source_status`, `list_upstream_incidents` e `lookup_customers`. O
  servidor deixou de ter `--agent`: anuncia todas as tools, e o nosso catálogo
  decide que agente usa cada uma.
- As 11 tools da base local passaram a ser **locais** (no mesmo processo).
- O catálogo indica a origem de cada tool (`local` ou `mcp`). O gateway ficou
  assíncrono e encaminha para a tool local ou para o cliente MCP, com os
  mesmos hooks e a mesma auditoria.
- **Fixação das tools MCP** (sessão 03): `tools/mcp_lock.json` guarda o hash
  do nome, descrição e parâmetros de cada tool revista. Uma tool nova ou
  alterada é bloqueada pelo hook antes da tool. Novo comando
  `data-quality-mcp-lock`.
- Migração 2: `tool_calls.source`; as chamadas MCP ficam associadas à
  execução investigada.
- A definição da pipeline indica a origem (`source_system`,
  `source_dataset`), devolvida pelas tools locais.
- Só o texto livre da origem (`list_schema_changes`,
  `list_upstream_incidents`) é marcado como não confiável. `get_run_logs` e
  `find_runbook` deixaram de ser marcados: os logs são gerados pela nossa
  pipeline e os runbooks são procedimentos nossos e revistos.

### Validação

- `uv run --locked --extra dev pytest -q` — 39 testes passaram, incluindo as
  tools MCP através do gateway com auditoria `mcp`, os erros da plataforma, o
  bloqueio de tools com descrição alterada ou não revista, o lock igual ao
  servidor, o ficheiro da plataforma igual ao `platform.sql` e a recusa de
  escritas pelo SQLite.
- Ligação real por stdio com `data-quality-mcp-lock`: as 5 tools fixadas.
- `uv build`: o ficheiro da plataforma, o `platform.sql` e o lock são
  incluídos no pacote.

### Ainda por fazer

Agentes PydanticAI, ações e aprovações (como tools locais), hook de fim de
execução, revalidação, retoma e memória.

## 2026-11-15 — Destino separado: três bases de dados

### Feito

- Os dados aprovados passaram para um ficheiro próprio, o destino
  `runs/warehouse.sqlite3` (tabela `pipeline_output`), como um data warehouse
  separado do sistema que controla a pipeline.
- A base de controlo `runs/pipelines.sqlite3` fica só com execuções, logs,
  lotes, findings, incidentes e auditoria. A migração 3 retira dela a tabela
  `pipeline_output`.
- Cada execução guarda em `pipeline_runs.destination` o caminho do destino; o
  histórico, a interface e `get_delivery_status` leem daí os registos
  entregues, sem criar o ficheiro se ele não existir.
- Novo argumento `--warehouse` no CLI; por omissão o destino fica ao lado da
  base de controlo. Um ficheiro de destino antigo continua a funcionar.
- Bases: destino (dados aprovados), controlo (histórico) e plataforma da
  origem via MCP (só leitura).

### Validação

- `uv run --locked --extra dev pytest -q` — 41 testes passaram, incluindo os
  dados aprovados só no destino, a base de controlo sem `pipeline_output`,
  um ficheiro de destino antigo que mantém os dados e a migração de uma base
  de controlo antiga.
- Execução pelo CLI: a base de controlo com o histórico e o destino com os 5
  registos aprovados.

### Ainda por fazer

Agentes PydanticAI, ações e aprovações (como tools locais), hook de fim de
execução, revalidação, retoma e memória.

## 2026-11-15 — Regras gerais e regras por pipeline

### Feito

- As regras continuam locais (não vêm do MCP; o MCP tem o contrato da origem).
- Nova biblioteca de regras gerais `simulator/rules/general.json`, aplicada a
  todas as pipelines: `expected-schema`, `minimum-volume` e `freshness`. São
  só regras do lote inteiro, porque as de campos dependem de cada pipeline.
- A definição da pipeline passa a ter `general_rules` (ajustar limite ou
  severidade, ou desativar, sempre com motivo) e `rules` (regras próprias).
  `orders_daily` ajusta o volume mínimo para 4 e a frescura para 60 min.
- `load_pipeline` junta as regras gerais ajustadas e as próprias; cada regra
  indica a origem e o motivo do ajuste, e as gerais desativadas ficam
  registadas. `list_quality_rules` devolve essa informação.
- Ids renomeados: `schema-v1` → `expected-schema`, `freshness-60m` →
  `freshness` (o limite deixou de fazer parte do nome).

### Validação

- `uv run --locked --extra dev pytest -q` — 47 testes passaram, incluindo a
  junção das regras, a desativação com motivo e a recusa de ajustes
  inválidos.

### Ainda por fazer

Agentes PydanticAI, ações e aprovações (como tools locais), hook de fim de
execução, revalidação, retoma e memória.

## 2026-11-15 — Organização dos módulos

### Feito

- Separados do motor do simulador o registo de eventos e a preparação de dados
  e falhas dos cenários.
- Separados do repositório de execuções a auditoria de tools e os modelos
  devolvidos pela persistência, mantendo os imports anteriores disponíveis.
- Separada a apresentação Streamlit da ligação entre interface e serviço.
- Documentada a organização no README, sem alterar o fluxo da pipeline.

### Validação

- `uv run --locked --extra dev pytest -q -p no:cacheprovider` — 47 testes
  passaram, incluindo a interface, persistência, simulador e MCP.

## 2026-11-15 — Agentes PydanticAI e correções no mesmo incidente

### Feito

- Implementada a equipa com orquestrador e especialistas de qualidade,
  diagnóstico, remediação e revisão. O orquestrador só delega; as consultas
  dos especialistas passam pelo catálogo e pelo gateway.
- As tools MCP chegam aos agentes com as descrições em texto e os esquemas
  aprovados. Foram acrescentadas referências de auditoria `tool_ref`.
- Outputs estruturados Pydantic, validação de referências observadas e
  confirmação determinística antes de aceitar uma resolução pelo modelo.
  Há limites de pedidos, chamadas, delegações e tempo de execução.
- Configuração OpenAI igual à do curso. Os agentes são opcionais no frontend
  e no CLI (`--agents`), sem credenciais nos ficheiros versionados.
- Migração 4: incidentes estáveis, tentativas de correção, investigações e
  passos dos agentes. Incidentes anteriores recebem uma associação inicial.
- O frontend aceita texto ou ficheiro JSON corrigido, com motivo e limite
  de 1 MB. Cada tentativa preserva o incidente e as regras originais, sem
  repetir as falhas sintéticas do cenário.
- Correções inválidas mantêm o incidente aberto. Só os lotes aprovados pelo
  gate são entregues; não é permitida uma segunda entrega do mesmo lote já
  carregado. A investigação/verificação pode ser repetida se tiver falhado.
- Os registos afetados são marcados como dados não confiáveis. Os logs e os
  runbooks mantêm o tratamento anterior.
- A interface apresenta conclusões, passos dos agentes e histórico das
  tentativas. Ajustada a duração de etapas quando uma investigação é reiniciada.

### Validação

- `uv run --locked --extra dev pytest -q -p no:cacheprovider` — 64 testes
  passaram. Chamadas a modelos externos estão proibidas na suite; os testes
  dos agentes usam `FunctionModel`.
- Verificadas descrições/esquemas recebidos pelo modelo, delegação, rejeição
  de evidências inventadas e de resolução sem recuperação, correções
  sucessivas no frontend, regras/destino originais e migração de incidentes antigos.
- `uv lock --check`, compilação dos módulos e `uv build` — concluídos.
  Confirmados os novos módulos e os dados incluídos no wheel.

### Ainda por fazer

Ações autónomas controladas, permissões e aprovações humanas, retoma de
processos interrompidos, memória, filtro de dados pessoais e avaliação dos
modelos reais com o conjunto de dados maior previsto para o final.

## 2026-11-15 — Harness evidente, ações automáticas e agentes sem registos

### O que foi feito

- O pacote `agents/` deu lugar a `harness/`, organizado como os
  `starter/harness.py` dos exercícios: um ficheiro por agente
  (`orchestrator.py`, `quality.py`, `diagnosis.py`, `remediation.py`,
  `reviewer.py`) com `INSTRUCTIONS`, `TOOLS` e as verificações do output, mais
  `specialists.py`, `hooks.py`, `policies.py`, `model.py` e `team.py` (que
  apenas liga as peças). O catálogo lê as permissões das listas `TOOLS`.
- Os hooks antes/depois de cada tool passaram do gateway para
  `harness/hooks.py`; o gateway continua a ser o único caminho e a auditar
  tudo.
- **Os agentes nunca recebem registos do lote.** Removida a tool
  `get_affected_records` e as referências `record:`; os agentes trabalham com
  regras, contagens, posições de linhas, perfis, logs e a plataforma da origem.
  `lookup_customers` (MCP) deixou de ser atribuída a qualquer agente.
- Duas ações automáticas para o agente de remediação, com política verificada
  em código (`harness/policies.py`) e ativada por pipeline no bloco
  `remediation` da definição:
  - `retry_ingestion`: só para `pipeline_failure`, se a plataforma MCP reporta a
    origem disponível (lido pelo código) e dentro de `max_automatic_retries` (2).
  - `quarantine_failed_records`: só com regras ao nível da linha e até
    `max_quarantine_fraction` (5 %); os restantes registos passam de novo por
    todas as regras.
- Cada ação cria uma nova tentativa do mesmo incidente; a equipa passa a
  trabalhar sobre ela e o revisor verifica-a. Ações recusadas ficam no audit
  como `blocked`, com o motivo.
- Migração 5: `incident_actions` (com índice único por tentativa e ação) e
  `quarantined_records`. O frontend mostra as ações e os registos em
  quarentena, só para revisão humana.
- Dataset com 40 encomendas; volume mínimo de 30; novo cenário
  `few_invalid_records.json` (2 em 40); `late_and_low_volume.json` com 25.
  Runbooks atualizados para a versão 2.

### Validação

- `uv run --locked --extra dev pytest -q -p no:cacheprovider`: 72 testes
  passaram. Novos testes cobrem o retry com revisão, a quarentena com 38
  entregues e 2 retidos, as recusas (origem `down`, demasiados registos,
  regras do lote, segunda execução, fora de uma investigação) e que nenhum
  resultado de tool enviado ao modelo contém identificadores de registos.
- `uv lock --check`, compilação dos módulos e `uv build`: concluídos.

### Ajuste à persistência da quarentena

- Migração 6 renomeia `quarantined_records` para `failed_records`, preservando
  as linhas já guardadas, e acrescenta o estado (`held`, `released` ou
  `discarded`), que começa em `held`.
- A tabela continua na base de controlo `pipelines.sqlite3`, separada do
  warehouse. A interface mostra o estado junto às linhas para revisão humana;
  ainda não há fluxo para o alterar.

### Ainda por fazer

Ações que exijam aprovação humana (por exemplo, alterar uma regra), retoma de
uma ação interrompida a meio, memória e avaliação com modelos reais.

## Próximos registos

Adicionar uma nova secção datada quando um marco for concluído. Atualizar este
ficheiro e os comandos relevantes no `README.md` nessa altura.
