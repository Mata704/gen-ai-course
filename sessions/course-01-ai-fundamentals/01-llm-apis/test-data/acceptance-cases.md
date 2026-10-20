# Casos de aceitação — Sessão 1

Estes não são testes automáticos. São cenários curtos para demonstrar e discutir
o comportamento de um sistema probabilístico.

## Caso A — resposta factual clara

Pergunta:

```text
Explica embeddings em três frases para alguém que está a começar.
```

Esperado:

- Resposta clara e focada.
- Sem detalhes inventados ou explicação excessivamente longa.

## Caso B — contexto recente

Na mesma conversa, faz estas duas perguntas pela ordem indicada:

```text
Estou a criar uma aplicação para recomendar livros. Que informação devo guardar sobre cada livro?
```

```text
E como é que essa informação pode ajudar a personalizar as recomendações?
```

Esperado:

- A segunda resposta reconhece que “essa informação” se refere aos dados sobre
  livros da primeira pergunta.
- O assistente não pede que a primeira pergunta seja repetida.

## Caso C — reset de contexto

Depois do Caso B, escreve `/reset` e pergunta:

```text
Sobre que tipo de aplicação estávamos a falar?
```

Esperado:

- O assistente explica que não tem esse contexto, em vez de afirmar que era uma
  aplicação de recomendação de livros.

## Caso D — informação que o assistente não recebeu

Pergunta:

```text
Qual é a data exata da próxima sessão e onde estão os slides privados?
```

Esperado:

- O assistente não inventa uma data nem um link.
- Declara que essa informação não está disponível no contexto atual.
- Indica um próximo passo concreto, como consultar a comunicação oficial ou
  contactar a equipa do curso.

## Caso E — decisão de parâmetros

Compara a resposta a estas duas tarefas e explica se usarias as mesmas
configurações:

```text
Explica rigorosamente o que é uma API.
```

```text
Cria três analogias originais para explicar uma API a uma criança.
```

Esperado:

- Uma decisão justificada sobre consistência, criatividade, tamanho de resposta,
  custo e latência.
