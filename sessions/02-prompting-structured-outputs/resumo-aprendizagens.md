# Resumo das aprendizagens - Sessão 2

Este ficheiro serve como guia de revisão e espaço para apontamentos. A sessão
explora como escrever prompts mais controláveis e como transformar respostas de
um LLM em dados que uma aplicação consegue validar e utilizar.

## Visão geral

Na sessão 1 construímos chamadas, conversas com contexto e streaming. Nesta
sessão damos o passo seguinte: separar o prompt do código, comparar versões,
fornecer contexto confiável, definir um formato de saída e tomar decisões
seguras a partir do resultado.

## Exercício 1 - Laboratório de prompts

### O que foi praticado

- guardar prompts em ficheiros externos ao código Python;
- carregar um prompt com `Path.read_text(encoding="utf-8")`;
- executar duas versões com exatamente a mesma mensagem do utilizador;
- comparar como instruções diferentes alteram a resposta;
- testar prompts com casos pequenos e repetíveis;
- observar o impacto de instruções sobre idioma, concisão, limites e
  tratamento de informação em falta.

### Evolução dos prompts

O prompt inicial é genérico: pede apenas uma resposta de suporte. A segunda
versão define um contrato mais explícito: responder apenas com a informação
fornecida, reconhecer quando falta informação e fazer uma pergunta de
seguimento focada.

### Ideias para apontamentos

- O que mudou entre as duas respostas?
- Que instrução teve maior impacto?
- Que comportamentos ainda ficaram ambíguos?
- Que exemplos acrescentaria para tornar o resultado mais consistente?

Notas:

<!-- Escreve aqui as tuas observações do exercício 1. -->

## Exercício 2 - Structured output

### O que foi praticado

- definir um contrato de dados com um modelo Pydantic;
- restringir valores possíveis com `Literal`;
- representar uma intenção, um resumo e a necessidade de follow-up;
- pedir uma resposta estruturada através de `responses.parse`;
- passar o schema com `text_format=CourseRequest`;
- obter o resultado validado em `response.output_parsed`;
- tratar o caso em que não existe um resultado estruturado utilizável;
- serializar o resultado para JSON com `model_dump_json`.

### Porque usar um schema

Texto livre é adequado para mostrar diretamente a uma pessoa, mas é frágil
quando outro componente precisa de tomar uma decisão. Um schema explicita o
contrato, limita categorias inválidas e permite que o código trabalhe com
campos previsíveis.

O schema também é uma decisão de produto. Categorias demasiado amplas perdem
informação; categorias demasiado específicas tornam a classificação difícil e
podem aumentar o uso de `other`.

### Perguntas para revisão

- Que pedidos pertencem a cada intenção?
- Quando deve ser usado `other`?
- Que campo seria útil acrescentar ao schema?
- O que deve acontecer quando a validação falha?

Notas:

<!-- Escreve aqui as tuas observações do exercício 2. -->

## Exercício 3 - Classificador de intenções

Este é o desafio principal da sessão. O objetivo é transformar uma mensagem de
suporte numa decisão de triagem segura.

### Estrutura do resultado

`IntentResult` inclui:

- `intents`: uma ou mais intenções classificadas;
- `confidence`: confiança baixa, média ou alta;
- `missing_information`: dados que ainda são necessários;
- `suggested_response`: resposta sugerida para o utilizador.

### Camadas de instrução

O ficheiro `course_rules.md` representa contexto confiável fornecido pela
aplicação. As instruções devem explicar ao modelo:

- quais são as regras oficiais que pode usar;
- como classificar pedidos com mais do que uma intenção;
- como lidar com informação ausente;
- que deve tratar a mensagem do utilizador como input, não como instruções
  confiáveis;
- que não deve revelar instruções internas, credenciais ou detalhes privados.

Uma regra importante é não interpolar a mensagem do utilizador nas instruções
confiáveis. O pedido deve continuar separado em `input`, para reduzir o risco
de confundir conteúdo do utilizador com regras da aplicação.

### Decisão segura

`next_action` converte o resultado do modelo numa ação visível ao utilizador.
Uma estratégia segura é:

- pedir uma pergunta de seguimento quando a confiança é baixa;
- pedir a informação listada em `missing_information` quando ela é essencial;
- só mostrar a resposta sugerida quando há informação suficiente e confiança
  adequada;
- nunca inventar horários, links, políticas ou decisões do instrutor;
- não revelar as regras internas quando o pedido tenta ignorá-las.

### Casos importantes

- Um problema técnico deve levar a uma pergunta pelo erro concreto.
- Uma pergunta sobre slides ou horários deve reconhecer que essa informação
  não está nas regras fornecidas.
- Feedback deve ser encaminhado sem ser confundido com uma dúvida técnica.
- Um pedido misto pode ter várias intenções e exigir mais do que uma ação.
- Uma tentativa de prompt injection deve ser tratada como `other` e não deve
  revelar o contexto confiável nem as instruções internas.

Notas:

<!-- Escreve aqui as tuas observações do exercício 3. -->

## Princípios transversais

### Prompts são artefactos versionáveis

Manter prompts fora do código facilita comparar versões, discutir alterações e
testar o mesmo input contra diferentes instruções.

### Contexto confiável deve ser separado do input

Regras da aplicação, contexto autorizado e mensagem do utilizador têm papéis
diferentes. Separá-los torna o comportamento mais claro e reduz confusão entre
dados e instruções.

### Estrutura não significa verdade

Um resultado validado pelo Pydantic garante que os campos respeitam o schema,
mas não garante que a classificação ou o conteúdo estejam corretos. Ainda é
necessário avaliar confiança, informação em falta e regras de negócio.

### Fallback faz parte do design

Um sistema robusto define o que fazer quando o modelo está incerto, quando não
tem contexto suficiente ou quando devolve um resultado inutilizável. Pedir uma
clarificação focada é preferível a tomar uma decisão inventada.

### Avaliar comportamento, não apenas formato

Os casos de teste devem verificar simultaneamente a classificação, o tratamento
de informação ausente, os pedidos com múltiplas intenções e a resistência a
tentativas de manipular as instruções.

## O que consigo fazer no final

Depois desta sessão devo conseguir:

1. escrever e comparar versões de um prompt;
2. incluir regras e contexto externo de forma explícita;
3. definir um schema pequeno e adequado ao problema;
4. pedir e validar uma resposta estruturada;
5. classificar pedidos com uma ou várias intenções;
6. distinguir baixa confiança de informação inexistente;
7. devolver um fallback seguro em vez de inventar uma resposta;
8. testar também casos ambíguos e tentativas de prompt injection.

## Perguntas finais

- Que parte do comportamento deve ser resolvida pelo prompt?
- Que parte deve ser validada pelo código?
- Que informação é confiável e quem a forneceu?
- Qual é a ação segura quando o modelo não tem dados suficientes?
- Que caso de teste ainda falta para confiar nesta solução?

Notas finais:

<!-- Regista aqui as conclusões principais da sessão. -->
pydantic formato json
Objetivo
excepções 
role
restrições
fine-tunning - muito especificos, treinar modelo 
rag -
prompting - 

passar exemplos errados
-perder contexto
-custo
-latência

prompt injection
Prompt injection é uma técnica de ataque em que o usuário tenta forçar a IA a seguir instruções maliciosas embutidas na entrada.
imagens dentro de um doc e um doc é info
regex tirar certas words mas imagem é visual -pode falhar até pela lingua
no deployment de modelos -> azure e badrock (Jellbrake) -> defesa contra prompt injection -> prompt shield -> aplicar quando adiciona dados externos
projeto -> avaliar custos? , dados externos?
modelos mais recentes já têm segurança mas podem não ser suficientes. modelos treinados até tempo X e o hacker pode ter encontrado outra maneira

prompts têm versionamento

drow io 
criar fluxo
excalidraw.com
streamlit