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
`order_id`, `customer_id`, `amount` e `status`. A pipeline de demonstração exige
pelo menos quatro registos, valores permitidos e clientes de referência
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
   emitir um incidente `pending_analysis`. A etapa fica `pending`; ainda não
   executa agentes nem ações corretivas.
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
- `stages`: estado de cada etapa, incluindo o ponto de intervenção futuro.
- `input_records`: lote recebido, incluindo falhas simuladas.
- `records`: lote após transformação, com as evidências dos problemas.
- `output_records`: registos efetivamente carregados e verificados.
- `incident`: motivo e referências para futura análise pelos agentes.
- `events`: eventos de progresso e logs por etapa, pela ordem em que ocorreram.

Um lote bloqueado não é enviado para SQLite, não apaga lotes anteriores e não
recebe uma correção automática fictícia. Uma falha da origem não executa o
bloco de Data Quality; uma falha no destino não é apresentada como sucesso.
Entradas inexistentes, JSON malformado ou estrutura inválida produzem erro
explícito, sem recorrer aos dados de demonstração.

O CLI devolve código 0 quando conclui a simulação, mesmo que o cenário resulte
em bloqueio ou falha. Consulta `pipeline_status` no JSON. Código 2 indica erro
de argumentos ou entrada inválida.

**Ainda por implementar:** agentes PydanticAI, ações corretivas, aprovações,
revalidação após ações, retoma e memória.

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
referências de evidência (`log:`, `finding:`, `record:`, `incident:`,
`runbook:`) e nunca revelam o cenário escolhido nem as linhas de log que só
existem para descrever a simulação; a interface marca essas linhas com
`[simulador]`.

| Sub-agent | Tools locais (base local) | Tools MCP (plataforma da origem) |
|---|---|---|
| `quality` | `list_quality_rules`, `get_quality_findings`, `get_affected_records`, `get_batch_profile`, `find_runbook` | `get_dataset_contract`, `list_schema_changes`, `lookup_customers` |
| `diagnosis` | `get_run_summary`, `get_run_logs`, `list_recent_runs`, `compare_with_last_success`, `get_incident`, `find_runbook` | `get_dataset_contract`, `list_schema_changes`, `get_source_status`, `list_upstream_incidents` |
| `remediation` | `get_incident`, `find_runbook` | `get_source_status`, `list_upstream_incidents` |
| `reviewer` | `get_quality_findings`, `get_run_summary`, `get_delivery_status` | `get_dataset_contract` |

O orquestrador não tem tools: recebe só um resumo inicial do incidente
(`context.incident_brief`) e delega aos sub-agents. O catálogo
(`tools/catalog.py`) indica a origem de cada tool e quem a pode usar.

Todas as chamadas, locais ou MCP, passam pelo mesmo `ToolGateway`
(`tools/gateway.py`):

- **Hook antes da tool:** a tool tem de estar na lista do agente, há um limite
  de chamadas por sessão e, se for MCP, tem de estar fixada no lock (ver
  abaixo); caso contrário, a chamada é bloqueada.
- **Hook depois da tool:** limita o tamanho do resultado e marca o texto livre
  escrito pela equipa da origem (alterações de esquema e incidentes da
  origem) para ser tratado como dados, nunca como instruções. Os logs são
  gerados pela nossa pipeline e os runbooks são procedimentos nossos e
  revistos, por isso não são marcados.
- Cada chamada, incluindo as bloqueadas ou inválidas, fica em `tool_calls` da
  base local, com a origem (`local` ou `mcp`).

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
iniciar execuções, escolher o cenário e acompanhar logs e métricas; não
contém regras de negócio.

- **Barra lateral:** cenário, destino SQLite, pausa visual por etapa e botão
  **Executar pipeline**.
- **Execução ao vivo**, ao estilo GitHub Actions: um grafo com as seis etapas
  (⚪ em fila, 🟡 em execução, ✅ concluída, ❌ falhou, ⏭️ ignorada, ⏸️ a
  aguardar agentes) e um bloco expansível por etapa com os seus logs.
- **Execuções:** as 50 execuções mais recentes guardadas em SQLite, com
  contagem por resultado; selecionar uma mostra métricas (registos recebidos e
  carregados, regras falhadas, linhas afetadas, atraso e duração), regras que
  falharam, incidente e dados do lote.

A pipeline demora milissegundos; a pausa visual (por omissão 0,8 s) só
abranda a apresentação para se ver a etapa atual e entra nas durações
mostradas. Pode ser posta a 0. O histórico vem de SQLite, por isso continua
disponível depois de fechar o browser ou reiniciar a interface.

O motor publica o progresso através de eventos (`stage_started`,
`stage_finished` e `log`), passados a `PipelineSimulator.run(..., on_event=...)`
e também guardados em `events` no resultado JSON do CLI.

## Testes

```powershell
uv run --locked --extra dev pytest
```

Consulte a [proposta de arquitetura](proposta-arquitetura.md) para as fases
seguintes e a correspondência com os exercícios do curso. O guia
[como vai funcionar o projeto](como-funciona.md) explica a ideia passo a passo.
O [registo de progresso](progresso.md) acompanha o que foi concluído em cada
marco.
