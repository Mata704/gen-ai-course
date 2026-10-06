# Apontamentos — Sessão 05

## Avaliação da baseline

- Split avaliado: `development`, com 5 perguntas.
- Métricas gerais: source recall `1.00`, cobertura factual `0.933`, resposta correta/abstenção correta `1.00`, validade das citações `1.00`, latência média de `2439 ms` e contexto médio de `506 tokens`.
- Caso que correu bem: Apollo 11. A resposta identificou Armstrong e Aldrin na superfície e Collins em órbita, com a fonte esperada.
- Nota sobre a Apollo 13: a resposta explicou por que o pouso foi cancelado e como o módulo lunar ajudou a tripulação. A pergunta não pedia a data do regresso, mas a lista de avaliação esperava também “17 de abril”. Por isso, a nota foi `0.67`, apesar de a resposta cobrir o que foi perguntado.
- Leitura simples: a baseline encontrou as fontes certas nos casos com resposta e soube não inventar uma resposta sobre experiências da Apollo 14. No entanto, uma boa recuperação e uma citação válida não garantem que a resposta inclua todos os factos importantes.
- Nota sobre as métricas: `retrieval_source_recall=1.00` só verifica se as fontes esperadas aparecem nos resultados. Não penaliza fontes extra nem a relevância de cada resultado; no caso sem fonte esperada, a métrica também vale automaticamente `1.00`. `citation_validity=1.00` verifica que as fontes citadas foram recuperadas, não que cada frase tenha sido validada semanticamente.

### O que estas métricas nos dizem

1. **Porque é que a Apollo 13 teve `0.67`?**
	A resposta explicou o que a pergunta queria saber. Mas a lista de respostas esperadas também incluía a data “17 de abril”, que a pergunta não pediu. Para a avaliação ser mais justa, podemos tirar a data da lista ou perguntar também quando a tripulação regressou.

2. **O que mostrar quando não há fonte esperada?**
	É mais claro mostrar `N/A`, que quer dizer “não se aplica”, em vez de `1.0`. Não havia uma fonte certa para encontrar, por isso não faz sentido dar uma nota de acerto ou erro nessa métrica.

3. **O que não conseguimos provar com estas duas métricas?**
	No exercício 1, este é apenas um exemplo hipotético: `source recall=1.0` só olha se encontrámos o ficheiro esperado, não se encontrámos a parte certa do texto. `fact coverage=1.0` só olha se as palavras esperadas aparecem, não se a frase está a dizer algo verdadeiro. Se os factos esperados forem “Apollo 7” e “Earth orbit”, a resposta “Apollo 7 esteve em Earth orbit e também aterrou na Lua” contém os dois factos esperados, mas acrescenta uma afirmação falsa. As métricas podem dar `1.0` mesmo assim. A resposta real do exercício não afirmou que a Apollo 7 aterrou na Lua.

## Comparação de retrieval

- Métodos comparados: semântico / lexical / híbrido
- Método que encontrou os chunks mais úteis: empate. Nos 4 casos com resposta, os 3 métodos encontraram a secção certa entre os 2 primeiros resultados (`recall@2 = 1.00`). Em 3 casos, a secção certa ficou logo em primeiro (`0.75`).
- Exemplo observado: na pergunta sobre a Apollo 7, o método lexical pôs a secção certa em primeiro; semântico e híbrido puseram a secção da Apollo 8 primeiro. Na pergunta sobre a Apollo 13 aconteceu o contrário: semântico e híbrido puseram a secção certa primeiro, e lexical deixou-a em segundo.
- Método escolhido e motivo: no desenvolvimento, os três empataram. O holdout favoreceu lexical e híbrido, mas não mostrou diferença entre esses dois métodos. Ainda não há dados suficientes para escolher um vencedor definitivo.
- Resultado no holdout: lexical e híbrido tiveram `recall@2 = 1.00` e posição média da primeira secção certa de `1.25`; semântico teve `recall@2 = 0.75` e posição média de `1.50`. Os três acertaram a primeira posição em 3 dos 4 casos (`0.75`).
- Porque o recall ficou igual no desenvolvimento: `recall@2` só pergunta se a secção certa aparece nos dois primeiros resultados; não se está em primeiro ou segundo. Como os três métodos encontraram todas as secções certas nesse grupo, todos tiveram `1.00`, mesmo com ordens diferentes.
- O que mudou no holdout: no caso Surveyor 3, lexical e híbrido encontraram a secção certa em segundo lugar; semântico não a encontrou nos dois primeiros. Por isso, o recall do semântico desceu. O resultado mostra que a ordem e a presença são coisas diferentes: o recall só mede a presença.
- Nota: a pergunta sem resposta esperada, sobre a Apollo 14, não entra nestas médias. O exercício só compara a ordem dos textos encontrados; não cria respostas nem avalia se seriam corretas.

## Comparação de versões RAG

- Decisão: não lançar. O quality gate falhou: a answerability da candidate foi `0.833`, abaixo do mínimo de `0.90`, e houve regressões em casos críticos.
- Melhoria observada: na pergunta sobre o Surveyor 3, a candidate corrigiu a resposta errada da baseline e identificou Apollo 12 e Surveyor 3 (`fact coverage` passou de `0.00` para `1.00`). Também incluiu a distância percorrida pelo rover na resposta sobre a Apollo 15 (`0.50` para `1.00`).
- Regressão ou risco importante: na pergunta sobre experiências da Apollo 14, a baseline disse que não tinha informação suficiente; a candidate afirmou que a Apollo 14 instalou experiências, sem suporte no corpus. Também deixou de mencionar factos importantes nas respostas sobre Apollo 13 e Apollo 17.
- Alguma métrica escondeu um erro? Sim. A `citation validity` média da candidate foi `1.00`, mas no caso da Apollo 14 citou um ficheiro que tinha sido recuperado e que não comprova a afirmação. A métrica verifica que o ficheiro citado foi recuperado, não que prove a resposta. A média de retrieval também foi `1.00`, mas para perguntas sem fonte esperada recebe automaticamente esse valor.

## Conclusões

- O que aprendi:
- Próxima alteração que testaria:
- Outras notas:

Correr o exercício 1
uv run python sessions/05-advanced-rag-evaluation/starter/01_evaluate_rag_baseline.py --split development --output sessions/05-advanced-rag-evaluation/reports/baseline-development.json

Correr o exercício 2
uv run python sessions/05-advanced-rag-evaluation/starter/02_hybrid_retrieval.py --split development --top-k 2

hit@k

uv run python sessions/05-advanced-rag-evaluation/starter/03_compare_rag_versions.py