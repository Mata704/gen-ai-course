# Curso 2 — Leituras recomendadas

Links para acompanhar os temas do curso. Não é necessário ler tudo antes das aulas; as leituras complementam os exemplos e a discussão. As referências de preparação do material estão separadas em [sources.md](sources.md).

## Arquitetura de agentes — Sessões 1 e 8

- [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
  - **Quando consultar:** no início do curso e ao comparar um agente com vários agentes.
  - **O que ler:** a distinção entre workflows e agentes, quando usar agentes e os padrões de composição.
  - **Para pensar:** que parte de uma tarefa precisa realmente de decisões do modelo durante a execução?
  - **Nota:** é um artigo de enquadramento publicado em 2024. Os exemplos de tooling devem ser confirmados na documentação atual; não é o guia de instalação do curso.

## MCP — Sessão 3

- [Model Context Protocol — Architecture overview](https://modelcontextprotocol.io/docs/learn/architecture)
  - **Quando consultar:** ao trabalhar a ligação entre uma aplicação e um servidor MCP.
  - **O que ler:** responsabilidades do host, client e server; capacidades e transportes.
  - **Para pensar:** onde corre a tool e que componente é responsável por cada ligação?

## Aprovação de ações — Sessão 5

- [PydanticAI — Deferred Tools](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/)
  - **Quando consultar:** ao trabalhar ações que precisam de aprovação humana ou de um resultado posterior.
  - **O que ler:** as secções sobre aprovação humana e pausa da conversa.
  - **Para pensar:** como se relacionam a ação pedida pelo modelo, a aprovação e as permissões da aplicação?

## Avaliação de agentes — Sessão 6

- [Anthropic — Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
  - **Quando consultar:** ao definir casos de teste e critérios de sucesso.
  - **O que ler:** a estrutura de uma avaliação e a distinção entre o percurso executado, a resposta e o resultado da tarefa.
  - **Para pensar:** que evidência demonstra que o agente resolveu a tarefa, além de ter produzido uma resposta convincente?
