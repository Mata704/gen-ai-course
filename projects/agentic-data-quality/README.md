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
Para receber um ficheiro JSON local e escolher o destino:

```powershell
uv run --locked data-quality-sim --input .\src\data_quality_agent\simulator\datasets\orders.json --database .\runs\pipelines.sqlite3
```

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
   intervalos, valores permitidos, referências, volume e atraso.
4. **Intervenção dos agentes:** se houver problemas, bloquear a entrega e
   emitir um incidente `pending_analysis`. A etapa fica `pending`; ainda não
   executa agentes nem ações corretivas.
5. **Revalidação:** ponto reservado para voltar a executar o mesmo bloco de
   qualidade após uma futura ação autorizada; por enquanto fica `skipped`.
6. **Carregamento:** apenas se o Data Quality passar, gravar na tabela
   `pipeline_output` de SQLite e reler os registos para confirmar o efeito.

O destino predefinido é `runs\pipelines.sqlite3`, relativo à pasta de execução.
Cada execução tem um `run_id` próprio e os lotes anteriores são preservados.
Os dados e achados são reproduzíveis com as mesmas entradas, regras e cenário;
o identificador de execução é sempre novo. A seed altera apenas a ordenação
dos dados internos de demonstração; ficheiros recebidos mantêm a sua ordem.

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

**Ainda por implementar:** agentes PydanticAI, ações corretivas, revalidação
após ações, retoma, memória e MCP. SQLite guarda atualmente apenas
a saída aprovada; incidentes e contexto bloqueado são apresentados no JSON,
mas ainda não têm persistência própria.

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
- **Execuções:** lista das execuções desta sessão do browser, com contagem
  por resultado; selecionar uma mostra métricas (registos recebidos e
  carregados, regras falhadas, linhas afetadas, atraso e duração), regras que
  falharam, incidente e dados do lote.

A pipeline demora milissegundos; a pausa visual (por omissão 0,8 s) só
abranda a apresentação para se ver a etapa atual e entra nas durações
mostradas. Pode ser posta a 0. O histórico de execuções existe apenas na sessão
do browser; a persistência das execuções ainda está por implementar.

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
