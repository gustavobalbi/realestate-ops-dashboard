# Cambará Empreendimentos — Teste Técnico (Analista de Soluções de Negócio)

Aplicação Django que lê e escreve diretamente na base SQLite fornecida
(`data_cambara.sqlite3`, cópia de `cambara_teste_tecnico.db`), com autenticação simples,
dashboards de negócio, um fluxo de venda/distrato com regra de negócio aplicada no
servidor, e um assistente de perguntas em linguagem natural (texto-para-SQL) sobre os
dados reais.

## Stack e por quê

- **Django 6 (Python), sem framework de frontend.** Escolhido por familiaridade e por
  concentrar autenticação, camada de leitura, camada de escrita e templates num único
  processo, o que é mais rápido de entregar corretamente no prazo do teste do que separar
  API + SPA.
- **SQLite direto**, sem ORM "redesenhando" a base: os 7 modelos em `negocio/models.py`
  são `managed = False` apontando para as tabelas originais (`db_table`), então o Django
  nunca cria, altera nem apaga essas tabelas — ele só lê e escreve nas linhas.
- **Gemini (`google-genai`), camada gratuita** para o assistente de linguagem natural,
  usado como texto-para-SQL (ver seção própria abaixo).

## Como rodar localmente

```bash
python -m venv venv
# Windows: venv\Scripts\activate   |   Linux/Mac: source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edite .env e cole sua chave em GEMINI_API_KEY (grátis em https://aistudio.google.com/apikey)

python manage.py migrate      # cria só a tabela de sessão do Django; não toca nas tabelas de negócio
python manage.py seed_auth    # define a senha de cada usuário (1ª palavra do nome + "123")
python manage.py runserver
```

Acesse `http://127.0.0.1:8000`. Login com qualquer e-mail da tabela `usuarios` (ex.:
`candidato@cambara-teste.com.br`) e a senha correspondente da tabela abaixo (cada usuário
seed tem uma senha própria depois de rodar `seed_auth` — ver limitações de autenticação
abaixo).

Sem uma `GEMINI_API_KEY` válida, todo o resto da aplicação funciona normalmente; só a
página **Assistente (IA)** mostra um erro explicando que a chave não foi configurada.

## Estrutura

```
config/            settings, urls, wsgi (projeto Django)
negocio/           app único com toda a lógica de negócio
  models.py        7 modelos managed=False mapeando as tabelas originais
  normalize.py     regras de canonicalização de status/nome (grafia inconsistente)
  auth.py          autenticação simples por sessão contra a tabela usuarios
  analytics.py     lógica das 4 perguntas de negócio da seção 4 do briefing, mais os
                   dados agregados das 5 seções do carrossel do dashboard
  geo.py           contorno do Brasil, contorno de cada UF e projeção lat/lon para os
                   3 mapas do dashboard (empreendimentos, vendas, clientes por estado)
  services.py      camada de escrita: registrar_venda / registrar_distrato
  nl_assistant.py  assistente de linguagem natural (texto-para-SQL com Gemini)
  data_browser.py  dados agregados da página "Dados" (tabelas normalizadas, paginadas)
  views.py / urls.py / forms.py
  templates/negocio/*.html
  templatetags/negocio_extras.py   filtro de template (nome + cidade/UF)
static/img/        logo, monograma e foto de fachada da Cambará (gerados/tratados
                    para este teste -- ver seção de identidade visual)
data_cambara.sqlite3   cópia de trabalho da base fornecida (commitada de propósito,
                        para o avaliador rodar sem precisar copiar o .db original)
Dockerfile / entrypoint.sh / .dockerignore   imagem usada pelo deploy opcional no Render
                                              (ver "Deploy" -- testados localmente)
scripts/migrar_para_azure_sql.py   migração opcional SQLite -> Azure SQL Database, só
                                    necessária se algum dia trocar o SQLite padrão por um
                                    banco de verdade (ver "Deploy")
.github/workflows/docker-build.yml   builda e publica a imagem no GitHub Container
                                      Registry a cada push em master (não é usado pelo
                                      Render, que builda o Dockerfile direto do repo;
                                      mantido para quem preferir puxar uma imagem já
                                      publicada em outro serviço)
startup.sh         comando de inicialização alternativo para Azure App Service, de uma
                    tentativa de deploy anterior (abandonada por limite de quota da conta
                    Azure) -- não é usado pelo caminho de deploy atual, mantido só de
                    referência
```

## Decisões de modelagem e tratamento de dados

A base tem inconsistências de grafia propositais (ex.: `unidades.status` aparece como
`"vendida"`, `"Vendida"`, `"VENDIDA"`). Em vez de reescrever as linhas históricas, a regra
foi: **nunca alterar dados históricos para "corrigir" grafia** — normalizar em Python na
hora da leitura (`negocio/normalize.py`), e escrever sempre com grafia canônica a partir
de agora (`negocio/services.py`). Isso evita perder rastro do que veio "sujo" da origem.
Pela mesma razão, as colunas de texto (status, modelo_negocio etc.) permanecem como vieram
na base — a comparação já é sempre case/accent-insensitive na leitura, então normalizar o
dado bruto não mudaria nenhum resultado, só apagaria um achado de qualidade de dados que o
teste pede para identificar.

As 6 colunas de data (`data_lancamento`, `data_venda`, `data_distrato`, `data_cadastro`,
e os dois `mes_referencia`) são declaradas como `DateField` em `negocio/models.py` — o
SQLite não impõe tipo de coluna, então isso não altera o schema real (a coluna continua
`TEXT` fisicamente, como confirmado via `PRAGMA table_info`); é só o Django passando a
devolver `datetime.date` em vez de string crua nessas colunas, o que deixa comparações e
agrupamentos por ano/mês mais corretos (antes eram feitos via fatiamento de string, ex.
`data_venda[:4]`).

**Achado de qualidade de dados (aplicado):** toda unidade com status bruto `"cancelado"`
(40 linhas) tem uma venda vinculada com status canônico `"distrato"` — correspondência de
100%. `"Cancelado"` e `"Distrato"` são duas grafias históricas diferentes para o mesmo
evento (uma venda que caiu e cuja unidade nunca voltou ao estoque disponível no cadastro),
não duas categorias reais — diferente das outras inconsistências deste projeto (que só
variam maiúscula/acento), essa é conceitual. Por isso `negocio/normalize.py:
norm_status_unidade` funde os dois no mesmo bucket canônico `"distrato"` (não existe mais
um bucket `"cancelado"` separado): na tela **Dados**, uma unidade que veio da base como
"Cancelado" já aparece e é filtrável como **DISTRATO**, igual a qualquer outra. Isso
também significa que, historicamente, um distrato **não** devolvia a unidade para
"Disponível" na base como veio. A camada de escrita desta aplicação segue a regra
explícita do briefing em vez do padrão histórico: **todo novo distrato devolve a unidade
para "Disponível"**, liberando-a para uma nova venda.

Verificado também: `unidades.status` e `vendas.status_venda` já são consistentes entre si
uma vez normalizados (nenhuma unidade "vendida" com venda "distrato" e vice-versa) —
então a única inconsistência real de estoque é a de `"cancelado"` acima.

**Achado de qualidade de dados:** de todas as `vendas` com `data_distrato` preenchida
(150 linhas), **37** ainda têm `status_venda` dizendo "ativa" (em alguma grafia) — o
sistema de origem falhou em atualizar esse campo ao registrar o distrato. `data_distrato`
é tratado como a fonte de verdade (`negocio/normalize.py:venda_esta_ativa`): uma venda com data de
distrato preenchida sempre conta como distrato, independente do que `status_venda` diga.
Isso afeta a pergunta 1 (velocidade de vendas) e a listagem de "vendas ativas" na camada
de escrita — sem essa correção, seria possível tentar registrar um segundo distrato numa
venda que, por essa lógica, já não está mais ativa. Na direção oposta, **9** linhas têm
`status_venda` canonicamente "distrato" mas `data_distrato` **nula** — aqui o status já
está certo, só falta a data (o sistema de origem não registrou quando aconteceu). Os dois
achados ficam visíveis na tela **Dados** (aba Vendas), sem duplicar coluna: a coluna
**STATUS** não mostra o texto bruto, mostra o resultado de `venda_esta_ativa()` — nas 37
linhas do primeiro achado ela já aparece como "DISTRATO" mesmo com o texto bruto dizendo
"Ativa" (e é assim que o filtro de Status funciona também, pela mesma regra); e a coluna
**DATA DE DISTRATO** mostra "SEM REGISTRO" (em vez do "--" genérico, que aqui sempre
significa "venda ainda ativa") exatamente nas 9 linhas do segundo achado.

**Tratamento de nulos:** auditei `NULL`/string vazia em todas as colunas das 7 tabelas.
Únicos campos com `NULL` real: `empreendimentos.observacoes` (20 de 22),
`obra_andamento.observacoes` (537 de 562) — ambos campos de anotação livre, opcionais por
natureza — e `vendas.data_distrato` (2.056 de 2.206), que é `NULL` para toda venda ainda
ativa mais as 9 linhas do achado acima (data nunca registrada apesar do distrato). Não há
chave estrangeira órfã em nenhuma tabela (`unidades.empreendimento_id`,
`vendas.unidade_id`/`cliente_id` sempre resolvem para uma linha existente). Ou seja: nesta
base, "valores nulos onde não deveriam existir" não se manifesta como um problema à parte
das inconsistências já documentadas acima — verificação feita, resultado limpo.

**Observações sem achado sólido por trás (checadas, não viraram "erro" nem tratamento):**
17 dos 22 empreendimentos estão com status `"Em obras"` há mais de um ano desde o
lançamento (o mais antigo, 3,3 anos) — poderia indicar obra parada, mas tentar confirmar
isso contra `obra_andamento.percentual_conclusao` (medição mais recente por
empreendimento) não deu nenhum sinal: a média de conclusão é praticamente igual entre
status ("Concluído" 90,2%, "Em obras" 91,4%, "Suspenso" 91,3%) e o único empreendimento em
`"Lançamento"` (ainda sem obra iniciada, por definição) aparece com **96,9%** concluído.
Diferente da coluna de custo (que bate 1:1 com `financeiro_mensal`, achado documentado na
seção Obra abaixo), `percentual_conclusao` não tem relação nenhuma com
`empreendimentos.status` nesta base — por isso a aplicação não usa essa coluna pra
validar/sinalizar nada sobre o status do empreendimento.

### As 4 perguntas de negócio (premissas adotadas)

1. **Velocidade de vendas** = vendas ativas (líquidas de distrato) / total de unidades
   cadastradas no empreendimento (estoque total ofertado, independente do status atual).
   Uma venda é "ativa" segundo `venda_esta_ativa()`: `data_distrato` preenchida sempre
   conta como distrato, mesmo nas 37 linhas onde `status_venda` ainda diz "ativa" (achado
   acima) — sem essa checagem a velocidade de alguns empreendimentos fica superestimada.
2. **Risco de estouro de custo** = soma de `custo_realizado_mes` menos soma de
   `custo_orcado_mes` de todas as medições em `obra_andamento`, por empreendimento;
   positivo = estouro, magnitude = essa diferença acumulada em R$.
3. **Clientes duplicados** = **não há indícios de cadastro duplicado nesta base.** A
   primeira versão deste dashboard flagueava homônimos (mesmo nome) como duplicados, mas
   a base tem e-mail, e o e-mail já é uma chave própria e distinta aqui: 2.691 clientes,
   2.691 e-mails distintos mesmo após normalizar caixa/espaços — zero repetições. O que
   existe são 196 grupos de homônimos (pessoas diferentes com o mesmo nome), mostrados no
   dashboard como "Nome — Cidade/UF" para deixar claro que são cadastros distintos. O
   dashboard também quantifica o erro que a primeira abordagem cometia: agregar por nome
   em vez de por uma chave distinta (e-mail) reduz artificialmente o número de "clientes"
   e infla o ticket médio por cliente (de ~R$ 3,16 milhões para ~R$ 3,32 milhões nesta
   base) — exatamente a distorção que a pergunta de negócio pede para expor, só que na
   direção oposta da intuição inicial: o risco aqui era criar duplicidade que não existe,
   não deixar passar uma que existe.
4. **Financeiro reportado vs. recalculado**: recalculado = `receita_reconhecida −
   custo_incorrido − despesas_corporativas_rat`; inconsistente quando
   `|recalculado − reportado| > R$ 0,01` (tolerância de arredondamento). Achado: 63 das 562
   linhas de `financeiro_mensal` são inconsistentes, atingindo 29 dos 43 meses e 18 dos 22
   empreendimentos — uma diferença acumulada (em módulo) de ~R$ 6,93 milhões. Hipótese mais
   provável (a confirmar): lançamento de custo/despesa em competência diferente da do
   relatório já publicado, ou uma rubrica que entra no resultado mas não está representada
   nas colunas desta tabela.

Cada premissa também aparece na própria tela do dashboard, ao lado do resultado — e, para
as duas perguntas que não viram gráfico (3 e 4), o diagnóstico completo com os números
acima fica disponível a um clique, no ícone "i" de cada seção (ver abaixo).

## Dashboard (tela inicial)

Um carrossel de 5 seções (setas ‹ › e título ao centro trocam de seção; o `hidden` de cada
`<section>` é alternado em JS puro, sem framework). Cada seção tem, ao lado do título, um
ícone **"i"** que abre um modal com o diagnóstico dos dados daquela seção — tabelas/colunas
usadas, critério adotado e o achado de qualidade de dados relevante. É esse ícone que
carrega a resposta às perguntas 3 (Clientes) e 4 (Financeiro) do briefing; a antiga seção
de texto corrido "Perguntas" foi substituída por essa versão consultável para não poluir a
tela com prosa.

- **EMPREENDIMENTOS** — mapa do Brasil (SVG) com um marcador por cidade, tamanho
  proporcional ao número de empreendimentos ali, tooltip com os nomes ao passar o mouse. O
  contorno é o path `brazilMainland` extraído do arquivo *"Brazil location map.svg"*
  (Wikimedia Commons, autor **NordNordWest**, licença
  [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/deed.pt_BR),
  https://commons.wikimedia.org/wiki/File:Brazil_location_map.svg), com as coordenadas de
  cada cidade projetadas para o mesmo espaço via projeção equirretangular
  (`negocio/geo.py:project`). Ao lado, os gráficos "Velocidade de vendas" (barras
  verticais, 3 piores em destaque) e "Risco de estouro de custo" (barras horizontais,
  destaque para acima da média do grupo).
- **CLIENTES** — mapa **coroplético** por UF: uma região por estado
  (`negocio/geo.py:UF_PATHS`, contornos derivados do dataset MIT
  [giuliano-macedo/geodata-br-states](https://github.com/giuliano-macedo/geodata-br-states),
  simplificados e projetados com a mesma `project()` do mapa acima), cor interpolada de
  branco (menor quantidade de clientes, e-mail distinto) a marrom (maior). Clicar num
  estado fixa uma tooltip com o detalhamento por cidade e por perfil de cliente. Ao lado,
  3 gráficos: frequência de compra por cliente (quantas vezes o mesmo cliente comprou),
  ticket médio por perfil e contagem de clientes por perfil.
- **VENDAS** — mesmo padrão de mapa, mas escopado a `data_distrato IS NULL` e com o
  tamanho do marcador proporcional ao volume de vendas ativas na cidade. Clicar num
  marcador fixa a tooltip; clicar num empreendimento dentro dela filtra os 3 gráficos ao
  lado para aquele empreendimento (payload JSON embutido via `json_script`, sem round-trip
  ao servidor). Os gráficos: vendas por período (barras por ano, com drill-down para os
  meses ao clicar), valor de vendas por forma de pagamento, e por tipo de unidade.
- **FINANCEIRO** — 3 cards com os números do achado da pergunta 4 (linhas, meses e
  empreendimentos inconsistentes), gráfico de magnitude acumulada por empreendimento e
  gráfico de inconsistências por período com o mesmo drill-down ano → mês da seção Vendas.
- **OBRA** — não responde a uma das 4 perguntas do briefing; cobre o resto de
  `obra_andamento` que não aparecia em nenhuma tela (`custo_orcado_mes`/
  `custo_realizado_mes` já alimentam "Risco de estouro de custo" em Empreendimentos).
  Gráfico de % de conclusão mais recente por empreendimento e de empreendimentos por
  `status`. O ícone "i" também documenta um achado da investigação:
  `financeiro_mensal.custo_incorrido` é exatamente igual a
  `obra_andamento.custo_realizado_mes` nas 562 linhas de ambas as tabelas — o "custo
  incorrido" do recálculo da pergunta 4 já é esse mesmo número, só duplicado em duas
  tabelas.
- **Botão flutuante "IA"**: abre o assistente de linguagem natural
  (`negocio/templates/negocio/assistente.html`), redesenhado como a tela inicial de um
  chat de IA — pergunta centralizada, chips de perguntas sugeridas, resposta/SQL/tabela
  aparecem abaixo após a primeira pergunta.

Os gráficos são HTML/CSS puro (sem biblioteca de gráficos): a altura/largura de cada barra
vem de uma porcentagem calculada em `negocio/analytics.py` e injetada via `style=""`. Isso
exigiu desabilitar a localização pt-BR nesses valores especificamente
(`{{ valor|floatformat:"2u" }}`) — com `USE_THOUSAND_SEPARATOR = True` ativo, o Django
formata números com vírgula decimal por padrão, o que quebra CSS/SVG (`height: 100,0%` não
é um valor válido).

## Página Dados (tabelas normalizadas)

Navegador somente-leitura de todas as tabelas de negócio (todas menos `usuarios`),
`negocio/data_browser.py`, uma aba por tabela, paginação de 25 linhas e **filtros por
coluna** (troca de aba/página/filtro via `fetch` para `/api/dados-tabela/`, com indicador
de carregamento -- a mesma preocupação de UX do Assistente, ver abaixo). Formato de
exibição, aplicado só na hora de montar a página (o dado bruto na base não muda, mesma
filosofia do resto do app):

- Toda coluna de texto em maiúsculo e sem acentuação (`negocio/normalize.py:
  maiusculo_sem_acento` -- cedilha e vogais acentuadas viram a letra base).
- Toda coluna de data formatada `dd/mm/aaaa`; nulo vira `--` (datas, `observacoes` e
  `data_distrato` de venda ativa) ou `SEM REGISTRO` no caso específico de
  `vendas.data_distrato` quando o status já é distrato mas a data nunca foi registrada
  (ver achado de qualidade de dados acima).
- Colunas com mais de uma grafia para o mesmo valor já saem canonicalizadas:
  `unidades.status` (que também funde `"cancelado"` em `"distrato"`, ver achado acima) e
  `empreendimentos.modelo_negocio` (`norm_modelo_negocio`) -- essa coluna tinha 9 grafias
  distintas para só 2 categorias reais ("Obra por Administração" e "SPE Incorporadora"),
  achado feito ao montar esta página.
- A coluna STATUS da aba Vendas vai um passo além de canonicalizar grafia: mostra o
  resultado de `venda_esta_ativa()` (a regra de negócio, não o texto bruto de
  `status_venda`) -- nas 37 linhas do achado acima ela já aparece "DISTRATO" mesmo com o
  texto bruto dizendo "Ativa". O filtro de Status segue a mesma regra, então filtrar por
  "Ativa" já exclui essas 37 linhas.
- Colunas de chave estrangeira (`empreendimento_id`, `unidade_id`, `cliente_id`) mostram o
  nome/identificador resolvido, não o número bruto, para ficar legível.
- **Filtros**: cada aba tem um filtro por coluna, de acordo com o tipo dela -- texto (busca
  por trecho, sem sensibilidade a acento -- mesmo critério do resto do app), seletor
  (colunas com poucos valores, incluindo as canonicalizadas/computadas), faixa numérica
  (mín./máx.) e faixa de data (de/até). Seletor e data aplicam na hora; texto e número
  aplicam ao clicar "Filtrar" ou apertar Enter (evita perder o foco a cada tecla digitada).

## Autenticação — o que É e o que NÃO é

Login funcional contra a tabela `usuarios` já existente, **sem** `django.contrib.auth`
(decisão deliberada: o briefing pede autenticação simples construída sobre os dados já na
base, não um sistema de produção). Implementação em `negocio/auth.py`:

- Senha comparada como `SHA-256(salt fixo + senha)` contra `usuarios.senha_hash`.
- `manage.py seed_auth` define a senha de cada usuário seed como a primeira palavra do
  próprio `nome` + `"123"` (ex.: "Diretoria Cambará" → `Diretoria123`) — substitui o
  placeholder `"trocar_no_setup"` que vinha na base por uma senha própria e memorável por
  usuário (ver tabela no fim deste documento).
- Sessão via `django.contrib.sessions` (cookie assinado, tabela `django_session`).

**Limitações conhecidas, documentadas conforme pedido no briefing:** salt fixo e global
(não por usuário), SHA-256 não é um KDF lento (vulnerável a força bruta comparado a
bcrypt/argon2), sem rate limiting/bloqueio de tentativas, sem expiração/rotação de senha,
sem RBAC — qualquer usuário autenticado acessa todas as telas (o campo `papel` é só
exibido na barra superior, não restringe nada). Nenhuma dessas lacunas é aceitável em
produção; são aceitáveis aqui porque o objetivo do teste é demonstrar o fluxo, não
endurecer segurança.

## Camada de escrita

`negocio/services.py` implementa as duas ações pedidas, cada uma em uma transação que
usa `select_for_update` para reler o status atual da linha antes de decidir — isso evita
a corrida de duas abas vendendo a mesma unidade ao mesmo tempo.

- **Registrar venda**: exige uma unidade com status canônico `disponivel` (o formulário já
  só lista essas, e o servidor confere de novo); cliente existente (busca por nome via
  endpoint JSON) ou novo cliente criado na hora. Grava a venda com status `"Ativa"` e
  atualiza `unidades.status` para `"Vendida"`.
- **Registrar distrato**: exige uma venda com status canônico `ativa`. Grava
  `status_venda = "Distrato"` e `data_distrato = hoje`, e devolve `unidades.status` para
  `"Disponível"` (ver decisão de modelagem acima).

Ambas levantam `RegraDeNegocioError` com uma mensagem explicando qual regra bloqueou a
ação, exibida ao usuário via Django messages.

## Assistente de linguagem natural (texto-para-SQL)

Abordagem escolhida para garantir que a resposta seja **rastreável aos dados reais e não
uma alucinação** (`negocio/nl_assistant.py`):

1. O Gemini recebe o schema das 7 tabelas (com aviso sobre grafia inconsistente, uma
   função SQL customizada `noaccent()` registrada na conexão para casar nomes/cidades
   mesmo sem acento, e uma nota explícita distinguindo `obra_andamento` (orçado vs.
   realizado) de `financeiro_mensal` (resultado contábil) — as duas tabelas têm colunas de
   "custo" e o modelo já confundiu as duas ao montar um JOIN) e gera **uma única consulta
   SELECT**.
2. A consulta é validada (só `SELECT`/`WITH`, sem `;`, sem palavras-chave de
   escrita/pragma) e executada numa conexão SQLite **aberta em modo somente-leitura**
   (`?mode=ro`), independente da conexão do Django — mesmo que a validação falhasse, o
   SQLite recusaria a escrita nessa conexão. Se a execução falhar (ex.: coluna na tabela
   errada), o erro real do SQLite é devolvido ao Gemini para autocorreção, até
   `MAX_TENTATIVAS_SQL` (3) tentativas, antes de desistir e mostrar o erro.
3. As linhas retornadas (dados reais) são devolvidas ao Gemini, que é instruído a
   responder **somente com base nelas** e a dizer explicitamente quando a tabela vier
   vazia, em vez de adivinhar.

A tela do assistente sempre mostra o SQL gerado e a tabela de resultados brutos ao lado
da resposta em texto, para o avaliador conferir a resposta contra os dados diretamente. O
envio da pergunta continua um POST normal (nada de `fetch`/SPA aqui, de propósito -- é o
componente mais sensível do app, então a interatividade nova não mexeu na lógica de
requisição), mas um overlay de carregamento aparece assim que o formulário é enviado; se
passar de 15s sem resposta, uma dica explica que o provedor pode estar sobrecarregado.

**Limitações conhecidas:** uma única consulta por pergunta (sem follow-up multi-turno),
sem cache de perguntas repetidas, sujeito a instabilidade/alta demanda do provedor Gemini
(código já faz retry com backoff em erros 5xx transitórios), e o modelo pode ocasionalmente
gerar SQL que não responde perfeitamente à pergunta — por isso o SQL fica sempre visível.

**Atenção para a demonstração:** a camada gratuita do Gemini tem cotas diárias baixas por
projeto/modelo (cada pergunta consome 2 requisições: gerar o SQL e depois gerar a resposta
em texto), e diferentes modelos têm cotas separadas — por isso o projeto usa
`gemini-3.1-flash-lite` por padrão (trocado a partir do `gemini-2.5-flash` original depois
de esgotar a cota dele em testes). Erros de cota (`429 RESOURCE_EXHAUSTED`) e de
sobrecarga (`503`) já aparecem como mensagem amigável na tela em vez de derrubar a
aplicação, mas vale confirmar a cota disponível (ou gerar uma chave nova / usar um projeto
com billing habilitado) antes da reunião do dia 08/09. `GEMINI_MODEL` no `.env` permite
trocar de modelo sem alterar código.

## Limitações gerais conhecidas

- Sem testes automatizados (fora do escopo dado o prazo; a lógica de negócio foi validada
  manualmente ponta a ponta, incluindo os dois fluxos de escrita e as 4 perguntas).
- `analytics.py` e a deduplicação de clientes carregam as tabelas relevantes inteiras em
  Python para normalizar/agrupar; funciona bem no tamanho desta base (milhares de linhas),
  mas não escalaria para milhões de registros sem mover a normalização para SQL/índices.
- O formulário de nova venda usa endpoints JSON simples (sem paginação) para
  unidades/clientes; adequado para 3.300 unidades e 2.691 clientes, não para uma base
  ordens de magnitude maior.
- `DEBUG = True` por padrão em `.env.example` — apropriado para rodar localmente na
  demonstração, não para deploy.

## Usuários de demonstração

Senha = primeira palavra do `nome` do usuário + `"123"` (definida por `manage.py seed_auth`).

| E-mail | Papel | Nome | Senha |
|---|---|---|---|
| diretoria@cambara-teste.com.br | diretoria | Diretoria Cambará | Diretoria123 |
| comercial@cambara-teste.com.br | comercial | Comercial Cambará | Comercial123 |
| engenharia@cambara-teste.com.br | engenharia | Engenharia Cambará | Engenharia123 |
| financeiro@cambara-teste.com.br | financeiro | Financeiro Cambará | Financeiro123 |
| candidato@cambara-teste.com.br | diretoria | Candidato Avaliador | Candidato123 |

## Deploy (opcional): Render

O teste pede só "rodar localmente" (seção 3 do briefing), então isto é opcional -- um
plus para quem quiser ver o app publicado, não parte da entrega.

**Por que Render:** builda o `Dockerfile` do repositório direto (sem precisar publicar a
imagem em nenhum registry separado), é um processo de verdade rodando o tempo todo -- sem
o timeout de ~10s que provedores serverless gratuitos (ex.: Vercel Hobby) costumam ter,
o que importa aqui porque o assistente de IA já foi observado levando 10-15s numa
pergunta só (até `MAX_TENTATIVAS_SQL` (3) chamadas sequenciais ao Gemini). E não exige
criar nenhum recurso de banco separado: o `data_cambara.sqlite3` já é committado no repo
e vai junto na imagem, então o app sobe direto em cima dele -- sem etapa de migração,
firewall ou credencial de banco.

**Limitação aceita:** o filesystem do container é recriado a cada deploy, então qualquer
venda/distrato registrado pela aplicação em produção é perdido no próximo deploy (volta
ao `data_cambara.sqlite3` do repositório). Para uma demonstração isso é uma vantagem, não
um problema -- garante que o avaliador sempre vê a base no estado esperado. Se um dia for
preciso persistir escritas de verdade, o caminho já existe: `config/settings.py` aceita
`AZURE_SQL_SERVER` (+ `_DATABASE`/`_USER`/`_PASSWORD`) para trocar o SQLite por um Azure
SQL Database de verdade, e `scripts/migrar_para_azure_sql.py` faz a migração inicial dos
dados -- só não é necessário para o deploy de demonstração no Render.

### Passo a passo

1. Crie uma conta em [render.com](https://render.com) (dá para logar direto com GitHub).
2. **New +** → **Web Service** → conecte o repositório
   `gustavobalbi/realestate-ops-dashboard`.
3. Render detecta o `Dockerfile` sozinho (**Language: Docker**). Deixe o **Root
   Directory** em branco (é a raiz do repo).
4. **Instance Type**: **Free**.
5. **Environment Variables** (aba do próprio formulário de criação, ou depois em
   **Environment** no serviço já criado):
   ```
   DJANGO_DEBUG=0
   DJANGO_SECRET_KEY=<gere uma nova -- nunca a do repositório>
   DJANGO_ALLOWED_HOSTS=<preencha no passo 7, depois que a URL existir>
   GEMINI_API_KEY=<sua chave>
   GEMINI_MODEL=gemini-3.1-flash-lite
   ```
   Não defina nenhuma variável `AZURE_SQL_*` -- assim o app usa o SQLite do repositório,
   como descrito acima.
6. **Create Web Service**. O primeiro build demora alguns minutos (instala o driver ODBC
   e as dependências Python, mesmo sem usar o driver nesse caminho -- é a mesma imagem
   documentada em `Dockerfile`).
7. Quando o deploy terminar, copie a URL gerada (algo como
   `https://realestate-ops-dashboard.onrender.com`), volte em **Environment**, preencha
   `DJANGO_ALLOWED_HOSTS` com esse hostname (sem `https://`) e salve -- isso dispara um
   redeploy automático. Sem esse passo o Django recusa a requisição com `Bad Request
   (400)` (`ALLOWED_HOSTS` vazio).
8. Acesse a URL e faça login com um dos usuários da tabela acima.

**Sobre o tier gratuito:** o serviço "dorme" depois de ~15 minutos sem receber
requisições; o primeiro acesso depois disso demora uns 30-50s para acordar (os
seguintes voltam ao normal). Deploy contínuo já vem ligado por padrão -- todo push em
`master` builda e sobe uma nova revisão automaticamente.
