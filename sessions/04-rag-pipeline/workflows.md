# Session 4: workflows dos exercícios

Execute os comandos a partir da raiz do repositório. Prepare o ambiente uma vez:

```bash
uv sync
```

Crie `.env` com `OPENAI_API_KEY` para os scripts que chamam os serviços OpenAI. Os testes locais não precisam de chave.

## Exercício 1: acompanhar o RAG completo

```bash
uv run python sessions/04-rag-pipeline/starter/01_rag_baseline.py --query "Which lunar region did Apollo 16 explore?" --show-loaded-pdf --show-context
```

- `load`: lê os quatro documentos Markdown e converte o PDF Apollo 16 para Markdown.
- `chunk`: usa um documento inteiro por chunk para criar uma baseline simples.
- `embed` e `store`: cria embeddings e grava-os numa coleção Chroma temporária.
- `retrieve`: escolhe os documentos mais semelhantes à pergunta.
- `augment`: mostra o contexto exato que será enviado ao modelo.
- `generate`: devolve resposta estruturada, possibilidade de abstenção e fontes.
- Observa a diferença entre operações determinísticas (leitura, ranking e contexto) e geração do modelo.

## Exercício 2: comparar estratégias de chunking

```bash
uv run python sessions/04-rag-pipeline/starter/02_chunking_lab.py --strategy both --chunk-words 90 --overlap-words 20 --top-k 2
```

- `fixed`: corta cada documento em janelas de palavras com sobreposição.
- `structure`: divide primeiro pelos títulos Markdown e corta secções longas; cada chunk conserva o título do documento e da secção.
- `overlap`: repete palavras entre janelas vizinhas para reduzir a perda de contexto nas fronteiras.
- `development`: compara a recuperação apenas nos casos de desenvolvimento; não usa os casos `holdout`.
- Compara tamanho/número de chunks e `source_recall`; inspeciona também nomes exatos, números, perguntas com vários factos e casos sem resposta.
- Experimenta outra configuração, por exemplo `--chunk-words 60 --overlap-words 10`, e compara os resultados.
- Exporta a estratégia escolhida para alimentar o exercício 3:

```bash
uv run python sessions/04-rag-pipeline/starter/02_chunking_lab.py --strategy both --chunk-words 90 --overlap-words 20 --export-strategy structure
```

- `chunk_words` tem de ser positivo; `overlap_words` tem de ser não negativo e menor que `chunk_words`.
- Os IDs são estáveis por origem, secção e posição. A sobreposição mantém as palavras nas fronteiras; não há truncagem silenciosa.

## Exercício 3: contexto limitado e citações

Depois de exportar chunks no exercício 2:

```bash
uv run python sessions/04-rag-pipeline/starter/03_grounded_rag.py --query "How far did Apollo 15 travel with the rover?" --max-context-tokens 450
```

Teste de abstenção:

```bash
uv run python sessions/04-rag-pipeline/starter/03_grounded_rag.py --query "What experiments did Apollo 14 deploy?"
```

- `select_context`: ignora resultados abaixo de `--min-score`, mantém a ordem do ranking e inclui apenas chunks completos que cabem no orçamento.
- O orçamento usa o contexto formatado, incluindo etiquetas de fonte e separadores, não apenas o texto dos chunks.
- `generate_grounded_answer`: faz uma chamada estruturada e pede resposta baseada apenas nas evidências selecionadas; sem evidência suficiente, deve abster-se.
- `validate_citations`: verifica que há citações numa resposta afirmativa, que não há citações na abstenção, que origem e chunk existem e que a citação textual está no chunk.
- A validação confirma a referência e a presença do excerto; não prova que cada afirmação da resposta é verdadeira. Confere manualmente se as citações sustentam as afirmações.

## Verificações locais sem API

```bash
uv run python -m unittest discover -s sessions/04-rag-pipeline/tests -v
```

Estes testes verificam chunking, orçamento e validação de citações. A execução dos scripts de embeddings e geração continua a exigir `OPENAI_API_KEY`.
