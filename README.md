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
  data_editor.py   edição de clientes/empreendimentos na página "Dados" (só essas duas)
  views.py / urls.py / forms.py
  templates/negocio/*.html
  templatetags/negocio_extras.py   filtro de template (nome + cidade/UF)
static/img/        logo, monograma e foto de fachada (tratados para este teste)
data_cambara.sqlite3   cópia de trabalho da base fornecida (commitada de propósito, pro
                        avaliador rodar sem copiar o .db original)
Dockerfile / entrypoint.sh / .dockerignore   imagem do deploy opcional no Render (ver
                                              "Deploy")
scripts/migrar_para_azure_sql.py   migração opcional SQLite -> Azure SQL, só necessária
                                    se trocar o SQLite padrão por um banco de verdade
.github/workflows/docker-build.yml   publica a imagem no GHCR a cada push (não usado
                                      pelo Render, que builda o Dockerfile direto)
startup.sh         comando de inicialização de uma tentativa anterior de deploy (Azure
                    App Service, abandonada por quota) -- não usado hoje, só referência
```

## Decisões de modelagem e tratamento de dados

Regra geral: **nunca alterar dados históricos.** A base tem grafia inconsistente
proposital (ex.: `unidades.status` como "vendida"/"Vendida"/"VENDIDA") — normalização
acontece só na leitura (`negocio/normalize.py`); escritas novas (`negocio/services.py`)
já saem com grafia canônica. O detalhe de cada achado abaixo (números, critério, como
verificar) está no ícone **"i"** da seção correspondente no dashboard e nos comentários de
`negocio/normalize.py` / `negocio/analytics.py` — aqui só a decisão tomada:

- **6 colunas de data → `DateField`** (`negocio/models.py`): não muda o schema real
  (SQLite não impõe tipo), só troca string crua por `datetime.date` nas comparações.
- **`unidades.status = "cancelado"` (40 linhas) fundido em `"distrato"`**
  (`norm_status_unidade`): mesma coisa, grafias diferentes — 100% das 40 têm venda
  vinculada com status "distrato". Não existe mais bucket "cancelado" separado; a tela
  Dados já filtra as duas como uma só.
- **Distrato sempre devolve a unidade pra "Disponível"** na escrita (`services.py`),
  mesmo a base histórica não fazendo isso.
- **`vendas.status_venda` divergente de `data_distrato`** nas duas direções: 37 linhas
  dizem "ativa" com distrato já registrado, 9 dizem "distrato" sem data registrada.
  `data_distrato` é sempre a fonte de verdade (`venda_esta_ativa()`); a tela Dados expõe
  os dois casos lado a lado (coluna STATUS já corrigida, "SEM REGISTRO" na data).
- **Nulos auditados nas 7 tabelas**: só existem em `observacoes` (2 tabelas, campo
  opcional) e `vendas.data_distrato` (semântica esperada) — nenhuma FK órfã.
- **`obra_andamento.percentual_conclusao` não valida `empreendimentos.status`**: checado
  e sem correlação nenhuma nesta base — por isso não é usado como sinal de erro.

### As 4 perguntas de negócio (premissas)

1. **Velocidade de vendas** = vendas ativas (`venda_esta_ativa()`) / unidades cadastradas
   no empreendimento.
2. **Risco de estouro de custo** = `custo_realizado_mes − custo_orcado_mes` acumulado por
   empreendimento (`obra_andamento`).
3. **Clientes duplicados**: não há — e-mail é a chave distinta (2.691 clientes, 2.691
   e-mails). O que existe são 196 grupos de homônimos, mostrados como "Nome — Cidade/UF".
4. **Financeiro reportado vs. recalculado** = `receita_reconhecida − custo_incorrido −
   despesas_corporativas_rat`; **63** das 562 linhas de `financeiro_mensal` são
   inconsistentes (~R$ 6,93 milhões acumulados).

Cada premissa aparece na tela do dashboard ao lado do resultado; para as perguntas 3 e 4
(sem gráfico), o diagnóstico completo fica no ícone "i" da seção.

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

Navegador de todas as tabelas de negócio (menos `usuarios`), `negocio/data_browser.py` —
aba por tabela, paginação de 25 linhas e **filtro por coluna** (texto sem sensibilidade a
acento, seletor, faixa numérica, faixa de data), tudo via `fetch` para
`/api/dados-tabela/` com indicador de carregamento. Formatação só de exibição, dado bruto
na base não muda: texto maiúsculo sem acentuação (`maiusculo_sem_acento`), data
`dd/mm/aaaa`, colunas de grafia inconsistente já canonicalizadas (`unidades.status`,
`empreendimentos.modelo_negocio`), FK mostram nome/identificador em vez do id. A coluna
STATUS de Vendas e o "SEM REGISTRO" na data de distrato seguem as mesmas regras descritas
acima.

**Edição (ícone ✎):** só em **Clientes** e **Empreendimentos** — as únicas duas tabelas
sem regra de negócio associada (`negocio/data_editor.py`). Unidades e Vendas continuam
somente-leitura aqui: editar `status`/`status_venda` direto bypassaria
`venda_esta_ativa()`/`UNIDADE_INDISPONIVEL`, então a forma de mudar o estado delas
continua sendo Nova venda / Registrar distrato, com a regra certa aplicada. Excluir é
bloqueado (com mensagem) quando há linha vinculada — as FKs desta base não têm constraint
no banco (`db_constraint=False`), então sem essa checagem a exclusão deixaria
`unidades.empreendimento_id`/`vendas.cliente_id` órfãos em vez de dar erro.

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

O teste pede só "rodar localmente" (seção 3 do briefing) — isto é opcional, não parte da
entrega.

**Por que Render:** builda o `Dockerfile` direto do repo (sem registry separado), roda
como processo real sem o timeout de ~10s comum em serverless gratuito (o assistente de IA
já levou 10-15s numa pergunta), e não exige banco separado — `data_cambara.sqlite3` vai
junto na imagem.

**Limitação aceita:** o filesystem do container reseta a cada deploy, então uma
venda/distrato registrado em produção some no próximo deploy (volta ao
`data_cambara.sqlite3` do repo — bom pra demonstração, garante que o avaliador sempre vê a
base esperada). Pra persistir escritas de verdade, `config/settings.py` já aceita
`AZURE_SQL_SERVER` + `scripts/migrar_para_azure_sql.py`, mas não é necessário aqui.

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
