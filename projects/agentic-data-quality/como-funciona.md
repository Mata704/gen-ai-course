# Como vai funcionar o projeto

Este guia explica a ideia de forma simples. A maior parte do fluxo descrito
abaixo **ainda será desenvolvida**. Para acompanhar o estado real do projeto,
consulta o [registo de progresso](progresso.md).

## 1. Qual é a ideia?

Imagina uma empresa que recebe diariamente uma lista de encomendas. Antes de
usar esses dados em relatórios, é importante verificar se estão corretos:

- Todas as encomendas têm cliente?
- Há encomendas repetidas?
- Os valores estão dentro dos limites esperados?
- Os dados chegaram a tempo?

O projeto simula uma **pipeline de ingestão**, com dados fictícios: recebe um
lote JSON, transforma os registos, verifica a qualidade e carrega os dados
aprovados em SQLite. Quando surgir um problema, os futuros agentes vão
intervir **a meio da pipeline**, antes do carregamento, para investigar e
solicitar ações. A pipeline não avança só porque um agente diz que está tudo bem.

## 2. Esquema geral

O seguinte esquema mostra o **funcionamento pretendido**, não o que já está
todo implementado:

```mermaid
flowchart TD
    A[Utilizador escolhe uma situação] --> B{Como começa?}
    B -- Executar cenário --> T[Ingestão do lote JSON]
    B -- Comunicar incidente --> F[Registar incidente e evidências]
    T --> U{Ingestão concluída?}
    U -- Não --> F
    U -- Sim --> W[Transformar e normalizar os registos]
    W --> C[Bloco de Data Quality determinístico]
    C --> D{Há problema?}
    D -- Não --> LOAD[Carregar dados aprovados em SQLite]
    LOAD --> V{Carregamento confirmado?}
    V -- Sim --> E[Apresentar resultado confirmado]
    V -- Não --> S[Manter problema por resolver e apresentar motivo]
    D -- Sim: bloquear carregamento --> F
    F --> G

    subgraph AG[Intervenção dos agentes]
        G((Orquestrador))
        G <-->|tarefa / resultado| QA[Sub-agent<br/>Qualidade dos dados]
        G <-->|tarefa / resultado| PD[Sub-agent<br/>Diagnóstico da pipeline]
        G <-->|tarefa / pedido de ação| RM[Sub-agent<br/>Remediação]
        G <-->|tarefa / veredicto| RV[Sub-agent<br/>Revisor]
    end

    subgraph TL[Camada de tools - controlada por hooks em código]
        HB{Hook antes da tool:<br/>tool permitida a este agente<br/>e a este utilizador?}
        TP[Tools Python locais:<br/>execução, registos, regras, métricas]
        MCP[Servidor MCP local:<br/>runbooks, incidentes, ações]
        HA[Hook depois da tool:<br/>auditoria e guardrails]
    end

    QA -->|chamada de tool| HB
    PD -->|chamada de tool| HB
    RV -->|chamada de tool| HB
    RM -->|pedido de ação| HB
    HB -- Consulta permitida --> TP
    HB -- Consulta permitida --> MCP
    TP --> HA
    MCP --> HA
    HA -->|resultado verificado| AG
    HB -- Recusada --> K[Recusar e devolver motivo ao agente]
    K --> AG

    HB -- Ação permitida --> L{Precisa de aprovação humana?}
    L -- Sim --> M{Pessoa aprova?}
    M -- Não --> N[Não executar, registar decisão e informar o orquestrador]
    N --> G
    M -- Sim --> O[Executar ação simulada através da tool MCP]
    L -- Não --> O
    O --> HA
    O --> P[Repetir as etapas afetadas e o bloco de Data Quality]
    P -->|nova evidência| G
    G --> HF{Hook no fim da execução:<br/>a conclusão tem evidência?}
    HF -- Não --> G
    HF -- Sim --> Q{Recuperação confirmada?}
    Q -- Sim --> LOAD
    Q -- Não, sem mais opções --> S
```

Os agentes **nunca acedem diretamente** aos dados, ao SQLite ou ao simulador:
tudo passa por tools. E todas as chamadas de tools passam por **hooks**, que
são verificações em código executadas sempre, seja qual for a decisão do
modelo.

O orquestrador **não segue uma ordem fixa**. Funciona como um coordenador:
recebe o incidente, decide que sub-agents chamar, recebe os resultados e decide
o passo seguinte. Pode chamar vários sub-agents em paralelo, voltar a chamar um
deles com mais contexto ou terminar quando não houver ações possíveis.

```mermaid
flowchart LR
    I[Incidente] --> O((Orquestrador))
    O -- "1. em paralelo" --> QA[Qualidade dos dados]
    O -- "1. em paralelo" --> PD[Diagnóstico da pipeline]
    QA -- achados --> O
    PD -- causa provável --> O
    O -- "2. se houver ação possível" --> RM[Remediação]
    RM -- pedido de ação --> O
    O -- "3. depois da revalidação" --> RV[Revisor]
    RV -- veredicto --> O
    O --> R[Decisão final]
```

Os números indicam um percurso típico, não uma sequência obrigatória. Os
sub-agents **só falam com o orquestrador**: não se chamam uns aos outros.

### O que acontece numa chamada de tool

```mermaid
sequenceDiagram
    participant SA as Sub-agent
    participant HB as Hook antes da tool
    participant T as Tool Python ou MCP local
    participant HA as Hook depois da tool
    participant DB as Registo SQLite

    SA->>HB: Quero usar a tool X com estes argumentos
    alt Tool não permitida ou argumentos inválidos
        HB->>DB: Registar recusa e motivo
        HB-->>SA: Recusado, com motivo
    else Permitida
        HB->>T: Executar com a identidade do utilizador
        T-->>HA: Resultado
        HA->>DB: Registar chamada, argumentos e resultado
        HA-->>SA: Resultado filtrado pelos guardrails
    end
```

| Hook | Quando corre | O que verifica |
|---|---|---|
| Antes da tool | Antes de cada chamada | A tool está na lista deste agente? O utilizador tem permissão? A ação exige aprovação? Os argumentos são válidos? |
| Depois da tool | Depois de cada chamada | Regista a chamada para auditoria e passa o resultado pelos guardrails (por exemplo, dados pessoais ou instruções escondidas nos logs). |
| Fim da execução | Antes da resposta final | A conclusão tem evidência de tools? Uma recuperação só é aceite se a revalidação a confirmar. |

Cada sub-agent só tem acesso às tools de que precisa:

| Sub-agent | Tools previstas | Origem |
|---|---|---|
| Qualidade dos dados | Consultar resultados das regras, registos afetados e métricas do lote. | Python local |
| Diagnóstico da pipeline | Consultar estado das etapas, logs, dependências e runbooks. | Python local e MCP |
| Remediação | Pedir ações como repetir a leitura da origem ou reprocessar um lote. | MCP (ações) |
| Revisor | Consultar o resultado da revalidação e o estado do destino. | Python local |
| Orquestrador | Nenhuma tool de dados; só delega aos sub-agents. | — |

Uma falha na pipeline ou numa ferramenta também deve ser apresentada como tal.
Se o sistema não conseguir confirmar o resultado, não deve dizer que o problema
ficou resolvido.

## 3. O que vai acontecer, passo a passo?

### Passo 1 — Escolher uma situação

A pessoa pode fornecer um ficheiro JSON local e escolher um cenário, ou usar
os dados fictícios já incluídos. Exemplos de cenários:

- execução normal;
- encomendas duplicadas;
- dados em falta;
- serviço de origem indisponível.

Também está previsto iniciar a investigação a partir de um incidente já
detetado, sem executar uma nova pipeline.

### Passo 2 — Executar e verificar os dados

O simulador lê os dados, faz uma transformação simples (normalizar o texto
de `status`) e entrega o lote a um bloco separado de regras determinísticas.
Esse bloco não usa IA: verifica os dados com critérios explícitos.

Se todas as regras passarem, os dados são carregados em SQLite e relidos para
confirmar o carregamento. Se houver problemas, os dados **não chegam ao destino**:
a pipeline fica bloqueada no ponto onde os agentes irão intervir.

Se a origem estiver indisponível, a execução falha e as verificações de
qualidade ficam marcadas como não executadas, em vez de aparecerem como
aprovadas.

### Passo 3 — Guardar e investigar o incidente

Atualmente, o incidente e as evidências aparecem no resultado JSON, com a
análise pendente. Mais tarde, o sistema também deverá persistir esse contexto
em SQLite para o tratamento e a retoma. O **orquestrador** — o agente que
coordena o trabalho — vai gerir uma equipa de **sub-agents** especialistas:

| Sub-agent | O que deverá fazer |
|---|---|
| Qualidade dos dados | Analisar regras, registos e métricas para perceber o que está incorreto. |
| Diagnóstico da pipeline | Consultar estado, logs e dependências para investigar uma causa provável. |
| Remediação | Solicitar uma ação simulada permitida, quando houver informação suficiente. |
| Revisor | Verificar o estado depois da ação e confirmar se o problema ficou resolvido. |

Como o orquestrador gere estes sub-agents:

1. **Decide quem chamar.** Uma origem indisponível pode precisar só do
   diagnóstico; registos duplicados precisam da análise de qualidade.
2. **Delega tarefas concretas.** Cada sub-agent recebe apenas a tarefa, a
   evidência necessária e as ferramentas que pode usar.
3. **Trabalha em paralelo quando faz sentido.** Qualidade e diagnóstico podem
   investigar ao mesmo tempo.
4. **Junta e avalia os resultados.** Se faltar evidência ou houver conclusões
   contraditórias, volta a delegar com perguntas mais precisas.
5. **Decide o passo seguinte.** Pede uma ação à remediação, pede confirmação
   ao revisor, ou termina com o problema por resolver.

O orquestrador não executa ações nem altera dados diretamente. Os sub-agents de
investigação só consultam informação. Mesmo quando o orquestrador decide
avançar, as permissões, as aprovações e o bloco de Data Quality continuam a ser
verificados em código.

### Passo 4 — Usar tools, MCP e hooks

Os sub-agents usam **tools** para obter informação, como consultar resultados
da pipeline ou ler um runbook. Um **runbook** é um procedimento documentado que
sugere como investigar ou tratar um problema.

- **Tools Python locais:** funções do projeto para consultas simples (regras,
  registos, métricas, estado das etapas).
- **Servidor MCP local:** uma forma padronizada de disponibilizar tools aos
  agentes. Vai expor os runbooks, os incidentes e as ações controladas.
- **Hooks:** verificações em código que correm antes e depois de cada tool e
  no fim de cada execução (ver a tabela na secção 2). As tools só fazem o seu
  trabalho; os controlos estão todos nos hooks, tal como na sessão 05 do curso.

Nem todas as tools estarão disponíveis para todos os sub-agents, e uma tool
chamada via MCP passa pelos mesmos hooks que uma tool Python.

### Passo 5 — Decidir se é possível agir

O sub-agent de remediação pode pedir uma ação simulada. Antes de a executar, o
hook antes da tool:

1. Verifica se o utilizador tem permissão para a ação.
2. Se a ação exigir aprovação, apresenta o pedido a uma pessoa.
3. Só executa se as permissões e, quando necessária, a aprovação forem válidas.

Uma aprovação não substitui a permissão necessária. Se a ação for recusada ou
rejeitada, o motivo e a decisão deverão ficar registados.

Por exemplo, um problema de ingestão poderá exigir **repetir a leitura da
origem quando esta recuperar** ou **reprocessar um lote depois de corrigido**.
Isolar registos inválidos também poderá ser uma opção, mas só com uma política
explícita: eliminar registos não equivale automaticamente a resolver o problema.
Estas ações ainda serão implementadas; os agentes não vão inventar dados em
falta nem ignorar as regras para fazer o lote passar.

### Passo 6 — Confirmar o resultado

Depois da ação, as etapas afetadas serão repetidas e o mesmo bloco de Data
Quality terá de passar novamente. O revisor deverá consultar essa evidência;
só então a pipeline poderá carregar os dados e apresentar a recuperação.

Se a ação falhar, se os dados continuarem incorretos ou se não for possível
confirmar o efeito, o problema permanecerá por resolver.

### Passo 7 — Mostrar e guardar o histórico

Uma interface Streamlit deverá mostrar as pipelines, incidentes, métricas,
agentes envolvidos, ferramentas usadas, aprovações, ações e resultados. O
histórico e o estado do workflow deverão ficar guardados em SQLite.

Se uma execução for interrompida, o sistema deverá conseguir retomá-la:
recuperar o estado, verificar novamente as permissões e confirmar se uma ação
já foi executada antes de tentar repeti-la.

## 4. Um exemplo completo

**Cenário futuro:** algumas encomendas aparecem duplicadas.

1. A pessoa fornece ou seleciona um lote e inicia a pipeline simulada.
2. Uma regra identifica que existem identificadores de encomenda repetidos.
3. A pipeline bloqueia o carregamento e emite um incidente com a regra e os
   registos afetados.
4. O orquestrador delega, em paralelo, a análise dos dados ao sub-agent de
   qualidade e a análise da execução ao sub-agent de diagnóstico.
5. Os sub-agents consultam evidências e runbooks e devolvem os resultados ao
   orquestrador, que os junta e decide se há uma ação possível.
6. Se houver, o orquestrador delega ao sub-agent de remediação a preparação de
   um pedido de ação. A ação concreta e a necessidade de aprovação serão
   definidas durante o desenvolvimento.
7. O sistema verifica a permissão e pede aprovação humana, se for necessária.
8. Se a ação for autorizada, executa-a e volta a processar e verificar o lote.
9. O orquestrador pede ao sub-agent revisor que avalie a nova evidência. Se
   os dados passarem as regras e o carregamento for confirmado, o incidente
   fica resolvido; caso contrário, o orquestrador pode tentar outra abordagem
   ou manter o carregamento bloqueado e explicar o que continua por resolver.

Esta é uma ilustração do fluxo pretendido. A correção e a verificação após a
ação ainda não existem no simulador atual.

## 5. Como será desenvolvido?

| Fase | O que vamos construir | Estado |
|---|---|---|
| 1. Fundação e simulador | Projeto UV, ingestão JSON, transformação, bloco de qualidade e carregamento SQLite. | **Implementação inicial disponível**, com ponto de intervenção pendente. |
| 2. Persistência e avaliação | Guardar execuções, incidentes e contexto bloqueado; criar casos de avaliação reproduzíveis. | Por fazer; só o destino dos dados aprovados já usa SQLite. |
| 3. Ferramentas e runbooks | Disponibilizar consultas, procedimentos e ações simuladas verificáveis. | Por fazer. |
| 4. Agentes | Criar o orquestrador e os sub-agents especialistas com PydanticAI. | Por fazer. |
| 5. Segurança e retoma | Aplicar permissões, aprovações, registo de decisões e recuperação após interrupções. | Por fazer. |
| 6. MCP e memória | Integrar ferramentas MCP locais e memória com origem e validade. | Por fazer. |
| 7. Interface e avaliação completa | Mostrar o sistema em Streamlit e testar o fluxo de ponta a ponta. | Por fazer. |

As fases serão validadas com testes à medida que forem construídas. A descrição
mais técnica está na [proposta de arquitetura](proposta-arquitetura.md).

## 6. O que já posso experimentar?

Hoje é possível executar a pipeline pela linha de comandos, receber um JSON
local e acompanhar as etapas no resultado. Os lotes aprovados são efetivamente
guardados em SQLite. Os lotes com problemas ficam bloqueados e devolvem um
incidente para futura análise pelos agentes.

As instruções de instalação, execução e teste estão no [README](README.md).
Ainda não existem agentes, interface Streamlit, persistência do contexto dos
incidentes, retoma ou ações corretivas. As etapas dos agentes e de revalidação
no resultado mostram os pontos de integração; não simulam trabalho já feito.

O projeto é local e usa dados fictícios. A escolha do modelo de IA ainda está
em aberto: usar um fornecedor remoto implicaria chamadas para fora da máquina.
