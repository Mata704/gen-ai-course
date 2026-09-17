# Sessão 1 — Exercícios: LLMs e APIs

## Objetivo

Transformar uma chamada simples a um LLM num assistente de aprendizagem com
streaming, comportamento claro, contexto limitado e decisões justificadas.

O ambiente já está preparado. Não há desafios de instalação, packages ou API
keys: o trabalho é desenhar o comportamento da aplicação.

## Antes de começar

Corre `01_first_call.py` e faz três perguntas:

1. Uma pergunta técnica clara.
2. Uma pergunta ambígua.
3. Uma pergunta sobre uma regra específica do curso que não foi fornecida ao
   assistente.

Em pares, identifica o que o programa já controla e o que ainda deixa ao acaso.

## Exercício 1 — contexto e streaming

Ficheiro: `starter/02_streaming.py`

O programa funciona, faz streaming e guarda o histórico, mas o assistente não
usa esse histórico. Melhora o comportamento sem alterar o ciclo principal.

### Requisitos

- Melhorar o contrato devolvido por `build_instructions()`.
- Implementar `build_input()` para usar uma janela limitada de contexto recente.
- Manter a pergunta nova claramente separada do contexto anterior.
- Garantir que `/reset` faz o assistente deixar de usar a conversa anterior.
- Manter a resposta em streaming.

### Casos de aceitação

Executa os casos A, B e C em
[`test-data/acceptance-cases.md`](test-data/acceptance-cases.md). Considera o
exercício concluído quando consegues demonstrar o comportamento esperado e
explicar a tua decisão de contexto.

### Pistas graduais

1. Começa por usar apenas uma interação anterior.
2. Experimenta uma janela pequena de mensagens recentes, em vez de todo o
   histórico.
3. Imagina que a conversa tem 100 mensagens: que parte ainda é útil para a
   pergunta atual?

## Exercício 2 — Smart Q&A responsável

Ficheiro: `starter/03_smart_qa.py`

O ciclo de terminal está pronto, mas as decisões principais do produto estão
por fazer. Completa as três funções marcadas sem alterar a assinatura delas.

### Requisitos

- `build_instructions()`: definir um contrato de assistente de aprendizagem
  claro e responsável.
- `build_input()`: incluir contexto relevante, mas limitado.
- `choose_generation_settings()`: devolver configurações justificadas para uma
  explicação factual.
- A resposta final deve continuar a ser apresentada em streaming.
- O assistente não pode inventar horários, links, regras ou decisões do curso
  que não recebeu.
- Perante informação insuficiente, deve dizer o que falta e indicar um próximo
  passo útil.
- O comando `/reset` tem de remover o contexto anterior.

### Demonstração final

Mostra o sistema a um colega ou ao docente com os casos B, C e D do ficheiro de
casos de aceitação. Explica em dois minutos:

1. O teu contrato para o assistente.
2. A regra usada para escolher contexto.
3. Uma configuração de geração e o respetivo trade-off.

### Pistas graduais

1. Faz primeiro uma versão que responda bem a uma única pergunta factual.
2. Só depois acrescenta uma interação anterior ao contexto.
3. Testa o caso de informação desconhecida antes de tentares otimizar o prompt.
4. Não procures uma resposta “perfeita”; procura uma decisão clara que passes a
   conseguir testar e defender.

## O que não é avaliado

- Ter a resposta com mais texto.
- Usar o prompt mais longo.
- Guardar todas as mensagens da conversa.
- Escolher valores de parâmetros sem conseguir explicar a razão.

## O que demonstra aprendizagem

- O assistente mantém contexto quando faz sentido e esquece-o após `/reset`.
- O assistente lida bem com incerteza, sem inventar informação.
- As decisões de prompt, contexto e parâmetros são explicadas com base nos
  resultados observados.
