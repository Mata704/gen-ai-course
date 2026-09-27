# Resumo das aprendizagens - Sessão 1

## Visão geral

Nesta sessão aprendemos a construir uma aplicação de perguntas e respostas
que comunica com um LLM através da API da OpenAI. A evolução dos três
exercícios mostra como passar de uma chamada mínima para uma aplicação
interativa, com contexto, streaming, controlo do comportamento e métricas de
execução.

## Exercício 1 - Primeira chamada ao LLM

No primeiro exercício aprendemos os fundamentos de uma integração com uma API
de modelos:

- carregar configurações locais a partir de variáveis de ambiente;
- validar a existência de `OPENAI_API_KEY` antes de fazer pedidos;
- criar um cliente `OpenAI` e escolher o modelo através de `OPENAI_MODEL`;
- enviar instruções do sistema e a pergunta do utilizador;
- ler o texto produzido através de `response.output_text`;
- validar a entrada do utilizador antes de chamar a API.

Também vimos que as instruções fazem parte do contrato da aplicação. Neste
caso, o assistente deve responder em português, ser conciso e pedir uma
clarificação quando a pergunta for ambígua, em vez de assumir uma resposta.

## Exercício 2 - Streaming e contexto recente

O segundo exercício transforma a chamada única numa conversa interativa.
Aprendemos a:

- receber a resposta por eventos com `stream=True`;
- apresentar cada fragmento assim que chega, reduzindo a latência percebida;
- juntar os fragmentos para guardar a resposta completa no histórico;
- manter turnos de utilizador e assistente numa estrutura simples;
- enviar apenas os dois turnos completos mais recentes;
- limpar o contexto com `/reset` e terminar a aplicação com `/quit`.

Esta limitação do histórico é uma decisão importante: o contexto enviado ao
modelo tem um custo e um tamanho finitos. Guardar apenas o necessário ajuda a
controlar custo, latência e previsibilidade, embora possa eliminar informação
mais antiga da conversa.

## Exercício 3 - Smart Q&A

O terceiro exercício reúne as técnicas anteriores e acrescenta preocupações
de uma aplicação mais próxima de produção:

- reforçar no prompt que o assistente não deve inventar datas, links,
  políticas ou decisões que não estejam no contexto;
- escolher parâmetros de geração de acordo com o tipo de tarefa;
- usar temperatura mais baixa e respostas limitadas para aprendizagem factual;
- permitir mais variedade e uma resposta ligeiramente maior para brainstorming;
- medir a latência total e o tempo até ao primeiro token;
- recolher tokens de entrada, saída e totais devolvidos pela API;
- estimar o custo com base no modelo e nos preços configurados;
- indicar quando não existe uma tabela de preços para o modelo usado.

O exercício mostra que uma integração com LLM não deve avaliar apenas a
qualidade do texto. Também é necessário observar velocidade, consumo de
tokens, custo e adequação dos parâmetros ao objetivo.

## Princípios transversais

### O prompt define comportamento

As instruções devem explicitar idioma, tom, limites e forma de lidar com
incerteza. Um prompt mais claro reduz respostas inventadas, mas não substitui
validação nem fontes de informação confiáveis.

### Contexto é uma decisão de produto

Uma conversa só parece contínua quando o histórico relevante é reenviado. O
comando `/reset` demonstra que apagar esse estado muda corretamente o
comportamento do assistente: sem contexto, ele deve admitir que não sabe.

### Streaming melhora a experiência, não a resposta

O streaming permite começar a mostrar o resultado mais cedo, mas a aplicação
continua a precisar de acumular os fragmentos para obter o texto final e
guardá-lo no histórico.

### Parâmetros dependem da tarefa

Explicações factuais pedem maior consistência e controlo do tamanho. Ideação
criativa pode beneficiar de maior variedade. A escolha deve considerar também
qualidade, custo e latência, e não ser igual para todos os pedidos.

### Métricas tornam o comportamento observável

Latência, tempo até ao primeiro token e tokens consumidos ajudam a perceber se
uma alteração melhorou a aplicação. A estimativa de custo é aproximada e deve
ser mantida sincronizada com o modelo e os preços efetivamente usados.

## O que conseguimos fazer no final

No fim da sessão conseguimos criar uma aplicação de terminal que:

1. lê uma pergunta e envia-a para um modelo;
2. responde progressivamente através de streaming;
3. mantém contexto recente e permite reiniciá-lo;
4. evita afirmar informação que não recebeu;
5. adapta a geração ao tipo de tarefa;
6. apresenta dados básicos de latência, tokens e custo.

Os casos de aceitação servem para verificar estes comportamentos com exemplos
concretos, lembrando que as respostas de um LLM são probabilísticas e devem ser
avaliadas pelo comportamento esperado, não apenas por uma saída exata.