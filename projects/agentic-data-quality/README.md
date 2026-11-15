# Sistema local de Data Quality baseado em agentes

Projeto independente com um simulador local de **ingestão de dados**:
recebe um lote JSON, transforma os registos, executa um bloco de Data Quality
determinístico e só carrega dados aprovados num destino SQLite.
Os agentes serão integrados no ponto de intervenção da pipeline, não apenas
numa conversa depois de a execução terminar.

## Configuração

Execute os comandos a partir desta pasta:

```powershell
uv sync --locked --extra dev
```

O projeto tem um `pyproject.toml` e `uv.lock` próprios. Não importa o pacote
principal do repositório nem o domínio da bolsa do Meridian.

## Organização do código

- `simulator/engine.py` coordena a execução; `input_data.py` trata os lotes
  e as falhas simuladas, e `events.py` regista o progresso das etapas.
- `persistence/repository.py` gere o histórico das execuções;
  `persistence/audit.py` gere a auditoria de tools e `models.py` os modelos
  devolvidos pelos repositórios.
- `tools/` contém as tools locais, o cliente MCP e o gateway; `mcp/` contém
  o servidor e a plataforma de origem simulada.
- `harness/` é o **harness dos agentes**, organizado como nos exercícios do
  curso (`starter/harness.py`): um ficheiro por agente com as instruções
  (`INSTRUCTIONS`), as tools (`TOOLS`) e as verificações do output em código.
  `specialists.py` tem o formato do relatório comum, `hooks.py` os hooks antes e
  depois de cada tool, `policies.py` quando uma ação automática pode correr,
  `model.py` o modelo e os limites, e `team.py` apenas liga as peças.
- `tools/actions.py` expõe as duas ações automáticas e
  `persistence/actions.py` guarda as ações e os registos em quarentena.
- `persistence/incidents.py` associa tentativas ao mesmo incidente e guarda
  as investigações dos agentes.
- `evaluation/` contém casos de aceitação versionados e um executor que verifica
  estados da pipeline, achados de qualidade e, opcionalmente, trajetórias dos
  agentes.
- `ui/app.py` liga a interface ao serviço; `ui/components.py` apresenta os
  resultados e `ui/view_model.py` prepara os estados e métricas.

## Executar o simulador

```powershell
uv run --locked data-quality-sim
uv run --locked data-quality-sim --scenario .\src\data_quality_agent\simulator\scenarios\quality_issues.json
uv run --locked data-quality-sim --scenario .\src\data_quality_agent\simulator\scenarios\source_unavailable.json
```

Sem `--input`, o simulador usa os dados sintéticos incluídos no pacote.
Para receber um ficheiro JSON local e escolher onde gravar:

```powershell
uv run --locked data-quality-sim --input .\src\data_quality_agent\simulator\datasets\orders.json --database .\runs\pipelines.sqlite3 --warehouse .\runs\warehouse.sqlite3
```

`--database` é a base de controlo (histórico) e `--warehouse` o destino dos
dados aprovados; sem `--warehouse`, o destino fica ao lado da base de controlo.

O ficheiro de entrada deve ser uma lista JSON de objetos com as colunas
`order_id`, `customer_id`, `amount` e `status`. A pipeline de demonstração
recebe cerca de 40 encomendas por dia e exige pelo menos 30 registos, valores
permitidos e clientes de referência
definidos na sua
[configuração de regras](src/data_quality_agent/simulator/definitions/orders_daily.json).
Usa apenas dados fictícios nesta fase.

## Etapas da pipeline

1. **Ingestão:** ler o lote JSON e aplicar as falhas do cenário.
2. **Transformação:** remover espaços exteriores e normalizar `status` para
   minúsculas, preservando a entrada original no resultado.
3. **Data Quality:** executar regras explícitas de schema, nulos, duplicados,
   intervalos, valores permitidos, referências, volume e atraso (ver
   "Regras de qualidade" abaixo).
4. **Intervenção dos agentes:** se houver problemas, bloquear a entrega e
   emitir um incidente. Com agentes ativados, o serviço investiga o contexto
   persistido; sem agentes, aguarda uma investigação ou um lote corrigido.
5. **Revalidação:** ponto reservado para voltar a executar o mesmo bloco de
   qualidade após uma futura ação autorizada; por enquanto fica `skipped`.
6. **Carregamento:** apenas se o Data Quality passar, gravar na tabela
   `pipeline_output` do destino (`runs\warehouse.sqlite3`) e reler os registos
   para confirmar o efeito.

O destino predefinido é `runs\warehouse.sqlite3`, relativo à pasta de execução.
Cada execução tem um `run_id` próprio e os lotes anteriores são preservados.
Os dados e achados são reproduzíveis com as mesmas entradas, regras e cenário;
o identificador de execução é sempre novo. A seed altera apenas a ordenação
dos dados internos de demonstração; ficheiros recebidos mantêm a sua ordem.

### Regras de qualidade

As regras são nossas e locais; não vêm do MCP. A plataforma da origem tem o
**contrato** do dataset (o que a origem promete enviar); as regras são o que a
nossa pipeline exige, e as duas coisas podem divergir.

- **Regras gerais**
  ([rules/general.json](src/data_quality_agent/simulator/rules/general.json)):
  aplicam-se a todas as pipelines e verificam o lote inteiro:
  `expected-schema`, `minimum-volume` (mínimo 1) e `freshness` (120 min).
- **Ajustes por pipeline:** a pipeline pode mudar o limite ou a severidade de
  uma regra geral, ou desativá-la (`"enabled": false`), sempre com `reason`.
  A `orders_daily` exige pelo menos 4 registos e atraso máximo de 60 min.
- **Regras próprias:** as regras de campos (nulos, duplicados, intervalos,
  valores permitidos e referências) dependem das colunas de cada pipeline e
  ficam só na sua definição.

Ao carregar a pipeline, as regras gerais (já ajustadas) e as próprias são
juntas numa só lista; cada regra indica a origem (`general` ou `pipeline`) e
o motivo do ajuste. É essa lista que fica guardada com cada execução e que
`list_quality_rules` devolve. Ajustes a regras inexistentes, limites que não
pertencem à regra ou regras próprias com o id de uma regra geral dão erro.

### Resultado e falhas

- `pipeline_status`: `succeeded` apenas após carregamento confirmado,
  `blocked` quando falha a qualidade, ou `failed` para falhas de execução.
- `quality_status`: `pass`, `fail` ou `not_run`.
- `stages`: estado de cada etapa, incluindo a intervenção dos agentes.
- `input_records`: lote recebido, incluindo falhas simuladas.
- `records`: lote após transformação, com as evidências dos problemas.
- `output_records`: registos efetivamente carregados e verificados.
- `incident`: retrato do incidente detetado nessa tentativa.
- `events`: eventos de progresso e logs por etapa, pela ordem em que ocorreram.

Um lote bloqueado não é enviado para SQLite, não apaga lotes anteriores e não
recebe uma correção automática fictícia. Uma falha da origem não executa o
bloco de Data Quality; uma falha no destino não é apresentada como sucesso.
Entradas inexistentes, JSON malformado ou estrutura inválida produzem erro
explícito, sem recorrer aos dados de demonstração.

O CLI devolve código 0 quando conclui a simulação, mesmo que o cenário resulte
em bloqueio ou falha. Consulta `pipeline_status` no JSON. Código 2 indica erro
de argumentos, entrada/configuração inválida ou falha da investigação dos agentes.

As ações automáticas reexecutam o gate numa nova tentativa do mesmo incidente.
O projeto também permite retomar ações interrompidas com a mesma chave de
execução, pedir aprovação humana para decisões sobre linhas falhadas e guardar
memória curta com evidência e validade.

## Agentes PydanticAI

Os agentes usam a mesma configuração OpenAI do curso: `OPENAI_API_KEY` e
`OPENAI_MODEL` no ambiente ou num `.env` local (o do projeto ou o do
repositório). O modelo predefinido é `gpt-4.1-mini`. Nunca coloques uma chave
nos ficheiros versionados.

```powershell
uv run --locked data-quality-sim --agents --scenario .\src\data_quality_agent\simulator\scenarios\quality_issues.json
```

No Streamlit, ativa **Investigar incidentes com agentes (OpenAI)** antes de
executar, ou usa **Investigar com agentes** num incidente existente. A opção
está desligada por omissão para continuar a permitir simulações sem API.
As chamadas enviam ao OpenAI o resumo do incidente e os resultados das tools:
regras, contagens, posições de linhas, perfis de colunas, logs e informação
da plataforma da origem. **Os registos do lote nunca são enviados aos
agentes.** Usa apenas os dados sintéticos do projeto. Não se efetuam chamadas
reais nos testes.

- O **orquestrador** só tem tools de delegação. Decide quem consultar e pode
  pedir investigações independentes em paralelo.
- **Qualidade** e **diagnóstico** investigam com as respetivas tools.
- **Remediação** escolhe o próximo passo e pode pedir uma das duas ações
  automáticas (ver abaixo); não altera regras nem escreve na origem.
- O **revisor** consulta a qualidade e a entrega da tentativa mais recente
  (corrigida ou criada por uma ação).
- As tools MCP chegam ao modelo com a descrição em texto e o esquema de
  parâmetros aprovados pelo lock, não com a hash. A execução continua a
  passar pelo gateway.

Os outputs são modelos Pydantic. Referências inventadas são rejeitadas;
`resolved` exige revisão independente e qualidade/carregamento confirmados
em código. Há limites de chamadas, delegações, pedidos ao modelo e tempo.
Falhas ficam explícitas na investigação guardada, sem se converterem em
sucesso. O relatório completo e os passos dos agentes são guardados na base
de controlo e apresentados no frontend.

### Onde está cada parte do harness

| Ficheiro (`src/data_quality_agent/harness/`) | O que define |
|---|---|
| `orchestrator.py` | instruções do orquestrador, `OrchestrationResult`, limites de delegação e `check_outcome` |
| `quality.py`, `diagnosis.py` | instruções e tools de cada especialista |
| `remediation.py` | instruções, tools e as duas ações (`ACTIONS`) |
| `reviewer.py` | instruções, tools e o critério de recuperação em código (`recovery_verified`) |
| `specialists.py` | instruções comuns, `SpecialistReport` e `check_report` |
| `hooks.py` | `before_tool` / `after_tool` (allowlist, orçamento, pinning MCP, tamanho, confiança) |
| `policies.py` | `check_retry` e `plan_quarantine` |
| `model.py` | modelo OpenAI e limites de pedidos, tools e tempo |
| `team.py` | liga as peças ao PydanticAI; não é preciso editá-lo para mudar o comportamento |

O catálogo de tools (`tools/catalog.py`) lê as permissões de cada agente da
lista `TOOLS` do seu ficheiro e recusa arrancar se um ficheiro listar uma
tool que não existe.

## Ações automáticas

O agente de remediação pode pedir duas ações de baixo risco. A política é
verificada **em código** (`harness/policies.py`) com factos guardados, antes
de qualquer execução; o modelo apenas pede. Cada pipeline ativa as ações no
bloco `remediation` da sua
[definição](src/data_quality_agent/simulator/definitions/orders_daily.json).

| Ação | Quando é permitida | O que faz |
|---|---|---|
| `retry_ingestion` | incidente `pipeline_failure`; a plataforma da origem (MCP) reporta a origem como `operational` ou `degraded`; ainda há tentativas no orçamento (`max_automatic_retries`) | volta a ler a origem numa nova tentativa do mesmo incidente |
| `quarantine_failed_records` | lote bloqueado só por regras ao nível da linha (não `minimum_rows` nem `freshness`) e registos falhados ≤ `max_quarantine_fraction` (5 %) | retém os registos falhados e processa os restantes numa nova tentativa, que volta a passar por todas as regras |

- O estado da origem para o retry é lido pelo código na plataforma MCP; não é
  o agente que o indica.
- Cada ação corre no máximo uma vez por tentativa (índice único na base), só
  durante uma investigação e só sobre a tentativa mais recente.
- Uma ação recusada pela política fica no audit como `blocked`, com o motivo,
  e o agente recebe esse motivo.
- O resultado devolve ao agente apenas o novo `run_id`, os estados e as
  contagens. A equipa passa a trabalhar sobre a nova tentativa e o revisor
  verifica-a; `resolved` continua a exigir a verificação em código.
- Os registos falhados ficam em `failed_records`, separados do warehouse, com
  estados `held`, `released` ou `discarded` (inicialmente `held`); aparecem no
  frontend, na secção **Ações automáticas**, apenas para revisão humana.
- Libertar ou descartar uma linha exige um pedido pendente e uma decisão de
  outra pessoa na interface. A política volta a validar que a linha continua
  `held`; a aprovação não autoriza por si só nem carrega a linha no warehouse.
  `Descartar` é uma disposição auditada, não uma eliminação física. A UI não
  autentica pessoas: os nomes indicados e o checkbox de confirmação são
  autorrelatados, não provam a identidade.
- A UI também permite propor um novo limite para `minimum_count` (1–1000) ou
  `maximum_delay_minutes` (0–1440). Um segundo decisor e a política em código
  têm de aprovar a alteração; só esses limites podem ser alterados e a nova
  versão aplica-se a execuções futuras, não às tentativas existentes.
- Se o processo for interrompido durante uma ação, **Retomar ações
  interrompidas** reutiliza o mesmo `run_id` idempotente; só sessões sem
  atividade há pelo menos 10 minutos podem ser retomadas.
- Os agentes podem consultar memória ativa da pipeline. O diagnóstico pode
  guardar uma nota curta apenas com referência a uma tool bem-sucedida e prazo
  (1–365 dias); o código rejeita dados pessoais detetados.
- O hook de saída mascara e-mails, telefones e NIFs portugueses detetados antes
  de devolver resultados aos agentes. É um filtro por padrões, não um sistema
  completo de deteção de identidade.

Cenários de demonstração:

```powershell
uv run --locked data-quality-sim --agents --scenario .\src\data_quality_agent\simulator\scenarios\source_unavailable.json
uv run --locked data-quality-sim --agents --scenario .\src\data_quality_agent\simulator\scenarios\few_invalid_records.json
```

O segundo tem 2 registos inválidos em 40 (5 %), por isso a quarentena é
permitida; em `quality_issues.json` (5 em 41) é recusada.

Alterações a regras de linha ou a outros atributos continuam indisponíveis.
## Corrigir um lote no mesmo incidente

1. Seleciona uma execução com incidente no histórico.
2. Na secção **Submeter correção para este incidente**, cola a lista JSON
   corrigida ou carrega um ficheiro JSON (máximo 1 MB), e indica o motivo.
3. Clica em **Validar e reprocessar correção**.

A nova tentativa mantém o mesmo identificador de incidente, mas recebe um
`run_id` próprio. Preserva as tentativas anteriores, utiliza a versão
original das regras e o destino, mantém a ordem recebida e não volta a injetar as falhas
sintéticas do cenário. O atraso sintético também não se repete: esta é uma
nova receção de dados.

O lote passa novamente pela ingestão, transformação e pelo mesmo gate
determinístico. Se falhar, o incidente mantém-se aberto e pode receber outra
correção. Se passar, é carregado e verificado por leitura. Com agentes
ativados, o revisor verifica esse resultado antes de o orquestrador resolver
o incidente; sem agentes, o serviço usa a confirmação determinística.

Um lote já carregado não pode ser novamente entregue como correção. Se a
investigação falhar após a entrega, usa **Investigar com agentes** para repetir
apenas a verificação. Correções simultâneas ou baseadas numa tentativa
desatualizada são recusadas. Não existe, ainda, recuperação automática de um
processo interrompido.

## Três bases de dados

| | Destino (warehouse) | Base de controlo (nossa) | Plataforma da origem (MCP) |
|---|---|---|---|
| Ficheiro | `runs/warehouse.sqlite3`, criado na primeira entrega | `runs/pipelines.sqlite3`, criado na primeira execução | `src/data_quality_agent/mcp/data/orders_platform.sqlite3`, já incluído no projeto |
| Dono | Os consumidores dos dados | Este projeto | A equipa que produz as encomendas (sistema externo simulado) |
| Acesso | Só a etapa de carregamento escreve | Leitura e escrita, com migrações | **Só leitura** (SQLite aberto com `mode=ro`) |
| Conteúdo | Só os dados aprovados (`pipeline_output`) | Execuções, logs, lotes, regras, findings, incidentes e auditoria | Contrato do dataset, alterações de esquema anunciadas, estado da origem, incidentes da equipa de origem e cadastro de clientes |
| Tools | Nenhuma escreve; `get_delivery_status` só confirma a entrega | Locais, no mesmo processo | Servidas pelo servidor MCP `orders-platform` |

### Destino: dados aprovados

Um ficheiro à parte, como um data warehouse real, que só recebe um lote
quando o Data Quality passou. Cada execução guarda em
`pipeline_runs.destination` o caminho do destino onde entregou, e é daí que
o histórico lê os registos entregues.

### Base de controlo: histórico em SQLite

Cada execução (CLI ou interface) é guardada em `runs/pipelines.sqlite3`. O
esquema é criado e atualizado por migrações versionadas
(`persistence/database.py`); a migração 3 retirou desta base a tabela
`pipeline_output`, que passou para o destino.

| Tabela | Conteúdo |
|---|---|
| `pipelines` | Definição da pipeline, versionada por hash do conteúdo. |
| `pipeline_runs` | Uma linha por execução: estado, qualidade, contagens, atraso e erros. |
| `run_stages`, `run_events` | Estado das etapas e logs, gravados **ao vivo** durante a execução. |
| `run_records` | Lote recebido e lote transformado, mesmo quando é bloqueado. |
| `quality_findings` | Resultado de cada regra do bloco de Data Quality. |
| `incidents` | Contexto do bloqueio ou da falha, para os agentes. |
| `tool_calls` | Auditoria de todas as chamadas de tools (locais e MCP): agente, origem, argumentos e resultado. |
| `incident_workflows`, `incident_attempts` | Incidente estável, tentativa atual e motivo de cada correção. |
| `agent_sessions`, `agent_steps` | Resultado ou erro de cada investigação e passos dos agentes. |

Uma execução interrompida por um erro de entrada fica registada como
`failed`. As escritas usam transações, e o modo WAL deixa a interface ler
enquanto uma execução decorre.

### Plataforma da origem: dados externos via MCP

Representa um sistema que não controlamos e que já tem dados antes de qualquer
execução. Os dados estão em `mcp/data/platform.sql` (legível) e no ficheiro
SQLite gerado a partir dele. O projeto nunca escreve nesse ficheiro; só quem
"mantém a plataforma" o regenera:

```powershell
uv run --locked python -m data_quality_agent.mcp.platform
```

O conteúdo dá pistas para os cenários sem revelar a resposta, por exemplo:
o estado `pending_review` foi acrescentado ao contrato (CHG-0412), a coluna
`campaign_code` só devia chegar em dezembro (CHG-0419), a origem está
degradada com exportações atrasadas e parciais (UPS-3307) e `C-999` é um
cliente de teste. Um dos incidentes tem um comentário a pedir para ignorar as
verificações de qualidade, para testar que os agentes tratam esse texto como
dados e não como instruções.

A definição da pipeline indica a origem (`source_system` e `source_dataset`),
e as tools locais devolvem esses valores para os agentes saberem o que
consultar na plataforma.

## Tools, hooks e servidor MCP

Os agentes nunca acedem diretamente a nenhuma das bases. Usam **tools** de
leitura que devolvem vistas pequenas e filtradas. As tools locais incluem
referências de evidência (`log:`, `finding:`, `incident:`, `runbook:`,
`action:`) e nunca revelam o cenário escolhido nem as linhas de log que só
existem para descrever a simulação; a interface marca essas linhas com
`[simulador]`.

| Sub-agent | Tools locais (base local) | Tools MCP (plataforma da origem) |
|---|---|---|
| `quality` | `list_quality_rules`, `get_quality_findings`, `get_batch_profile`, `find_runbook` | `get_dataset_contract`, `list_schema_changes` |
| `diagnosis` | `get_run_summary`, `get_run_logs`, `list_recent_runs`, `compare_with_last_success`, `get_incident`, `find_runbook` | `get_dataset_contract`, `list_schema_changes`, `get_source_status`, `list_upstream_incidents` |
| `remediation` | `get_incident`, `find_runbook`; ações `retry_ingestion` e `quarantine_failed_records` | `get_source_status`, `list_upstream_incidents` |
| `reviewer` | `get_quality_findings`, `get_run_summary`, `get_delivery_status` | `get_dataset_contract` |

O orquestrador não tem tools: recebe só um resumo inicial do incidente
(`context.incident_brief`) e delega aos sub-agents. O catálogo
(`tools/catalog.py`) indica a origem de cada tool; quem a pode usar vem da
lista `TOOLS` de cada ficheiro do harness. `lookup_customers` (MCP) não é
dada a nenhum agente, porque precisaria de identificadores tirados dos
registos.

Todas as chamadas, locais ou MCP, passam pelo mesmo `ToolGateway`
(`tools/gateway.py`), que aplica os hooks de `harness/hooks.py`:

- **Hook antes da tool:** a tool tem de estar na lista do agente, há um limite
  de chamadas por sessão e, se for MCP, tem de estar fixada no lock (ver
  abaixo); caso contrário, a chamada é bloqueada.
- **Hook depois da tool:** limita o tamanho do resultado e marca o texto livre
  escrito pela equipa da origem (alterações de esquema e incidentes da
  origem) para ser tratado como dados, nunca como instruções. Os logs são
  gerados pela nossa pipeline e os runbooks são procedimentos nossos e
  revistos, por isso não são marcados.
- Cada chamada, incluindo as bloqueadas ou inválidas, fica em `tool_calls` da
  base local, com a origem (`local` ou `mcp`). Resultados válidos incluem
  `tool_ref`, que os agentes podem citar.

Os **runbooks** (`src/data_quality_agent/runbooks/*.md`) são os procedimentos
versionados que a tool local `find_runbook` associa às regras falhadas.

### Servidor MCP

O servidor `orders-platform` (stdio) é o sistema externo: não conhece os
nossos agentes e anuncia as suas 5 tools a quem se ligar. Quem decide que
agente usa cada tool é o nosso lado, no catálogo e no gateway. O cliente
(`tools/platform_client.py`) arranca o servidor como processo filho.

```powershell
uv run --locked data-quality-mcp                      # arrancar o servidor (stdio)
uv run --locked data-quality-mcp-lock                 # ver as tools e se estão fixadas
uv run --locked data-quality-mcp-lock --update-lock   # aceitar as tools atuais depois de as rever
```

Como na sessão 03 do curso, a descrição e os parâmetros de cada tool MCP
ficam fixados por hash em `tools/mcp_lock.json`. Se o servidor mudar uma
descrição ou acrescentar uma tool, essa tool é bloqueada até alguém a rever e
atualizar o lock.

## Interface Streamlit

```powershell
uv run --locked data-quality-ui
```

Abre `http://localhost:8501` (só escuta em `localhost`). A interface serve para
executar e acompanhar todos os fluxos existentes, sem transferir regras de
negócio do serviço para a apresentação.

- **Execuções:** exemplos incluídos ou lote próprio colado/carregado em JSON
  (até 1 MB, sem falhas injetadas no modo próprio), histórico das execuções
  principais, incluindo as que ainda não têm resultado final. Tentativas
  automáticas de retry/quarentena não criam outra entrada: os seus blocos
  continuam o grafo depois da intervenção do agente. Correções manuais
  continuam a ser entradas independentes.
- **Intervenção:** submissão de correções, investigação com agentes, retoma
  de sessões/ações interrompidas, quarentena, pedidos e decisões de aprovação
  de linhas e de thresholds. As mesmas políticas continuam a ser aplicadas.
- **Agentes e tokens:** relatórios, passos, modelos/fornecedores usados,
  tokens de entrada/saída, pedidos e erros, latência por pedido e p50/p95.
  Valores da execução principal e secções expansíveis, fechadas por omissão,
  por tentativa automática. Os totais gerais ficam em Observabilidade e
  contam cada pedido uma só vez.
- **Logs e auditoria:** timeline de pipeline, agentes e tools com pesquisa,
  filtros de nível/origem e exportação JSON, com secções expansíveis por
  tentativa automática. Mostra também bloqueios e latência das tools.
- **Dados e regras / Memória:** consulta e exportação dos lotes, regras
  históricas da execução e memória da pipeline com origem/validade, incluindo
  a consulta de notas expiradas. A UI não escreve memória fora do fluxo do diagnóstico.
  Dados e métricas das tentativas automáticas também ficam em secções expansíveis.
- **Avaliação:** seleção de casos, execução determinística ou com agentes,
  taxa de aprovação, esperado versus observado, duração, tokens e logs por
  caso. Relatórios ficam na base de controlo; os SQLite dos casos ficam numa
  subpasta `evaluations/`, separados dos dados operacionais.
- **Observabilidade:** totais por modelo de todas as execuções da base de
  controlo e acesso aos logs das execuções selecionadas. O consumo de avaliações
  é apresentado na área de avaliação, não misturado com os totais operacionais.

O ID visível no histórico e no cabeçalho mantém-se o da execução principal;
o estado apresentado acompanha a tentativa automática mais recente. Cada
tentativa continua a ter um ID técnico próprio em SQLite para auditoria e
idempotência, consultável nos detalhes. A seleção de um ID secundário antigo
é encaminhada para a execução principal. As métricas/resultados iniciais
podem ser abertos sem confundir uma falha inicial com a entrega posterior.
Uma investigação pode atravessar várias tentativas: os pedidos ao modelo
usam a tentativa capturada no início do pedido, enquanto o relatório e os
passos da investigação mantêm a execução onde a sessão começou.

Não são calculados custos monetários. Os tokens vêm do uso reportado pelo
modelo (ou pelo modelo simulado em testes), não de uma estimativa do texto.
Pedidos falhados sem uso reportado ficam com tokens desconhecidos (`N/D`);
`≥` assinala totais parciais. Execuções anteriores à migração de telemetria não
têm consumo recuperável. A latência mede o pedido completo, não o primeiro token.
Não são guardados prompts/respostas na tabela de telemetria.

Os controlos ficam diretamente na barra lateral, sem painel de configuração
expansível nem pausa visual artificial. As métricas usam cartões compactos.
A UI usa sempre `runs\pipelines.sqlite3` como base de controlo, relativo à
pasta onde é iniciada; o warehouse fica em `runs\warehouse.sqlite3`. Para
usar os mesmos ficheiros, inicia a UI a partir da pasta do projeto. O histórico
sobrevive a reinícios. O CLI mantém a opção de escolher outra base.

**Clean**, na barra lateral, pede confirmação antes de apagar os dados da base
de controlo da UI (incluindo logs, agentes, telemetria, memória, aprovações,
overrides e relatórios), as entregas do warehouse associado e os dados das bases
dos casos em `evaluations/evaluation-*/`, na mesma pasta. Inclui avaliações sem
relatório final guardado. Os esquemas SQLite são preservados, sem dados de execução.
Depois da limpeza, a sessão visual volta a Execuções, com seleções, formulários e
agentes repostos.
Os cenários, lotes sintéticos e a origem MCP só de leitura nunca são alterados.
Confirma apenas quando não houver execuções em curso; o reset entre ficheiros
SQLite não é uma única transação e eventuais falhas são apresentadas na UI.

O motor publica o progresso através de eventos (`stage_started`,
`stage_finished` e `log`), passados a `PipelineSimulator.run(..., on_event=...)`
e também guardados em `events` no resultado JSON do CLI.

## Avaliação

Executa os seis cenários versionados sem chamar modelos:

```powershell
uv run --locked data-quality-eval
```

O modo padrão verifica estados de pipeline e de qualidade, achados obrigatórios
e quantidade entregue. Para avaliar também as decisões e a trajetória dos
agentes, ativa o modelo configurado no `.env` ou no ambiente:

```powershell
uv run --locked data-quality-eval --agents
uv run --locked data-quality-eval --agents --scenario orders-source-unavailable
```

O modo `--agents` verifica o estado esperado do incidente, os papéis que
participaram, as ações executadas e a quantidade final entregue. Os critérios
não avaliam a semântica do texto livre do diagnóstico: referências de evidência
e contratos estruturados continuam a ser verificados pelo harness. Este modo
faz chamadas ao modelo e pode ter custos; o nome configurado fica no relatório.
Usa `--output .\runs\evaluation.json` para guardar o relatório JSON, e
`--workdir .\runs\evaluation` para preservar as bases SQLite de cada caso.
O comando termina com código 0 se todos os casos passarem, 1 se houver casos
reprovados e 2 se a avaliação não puder ser executada.
Os relatórios também incluem duração por caso e telemetria dos modelos, mesmo
quando os SQLite temporários não são conservados. As avaliações iniciadas no
CLI devolvem o relatório; as iniciadas na UI são guardadas no histórico da UI.

## Testes

```powershell
uv run --locked --extra dev pytest
```

Consulte a [proposta de arquitetura](proposta-arquitetura.md) para as fases
seguintes e a correspondência com os exercícios do curso. O guia
[como vai funcionar o projeto](como-funciona.md) explica a ideia passo a passo.
O [registo de progresso](progresso.md) acompanha o que foi concluído em cada
marco.
