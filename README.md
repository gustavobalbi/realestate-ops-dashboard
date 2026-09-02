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
python manage.py seed_auth    # troca o placeholder "trocar_no_setup" em usuarios.senha_hash por um hash real
python manage.py runserver
```

Acesse `http://127.0.0.1:8000`. Login com qualquer e-mail da tabela `usuarios` (ex.:
`candidato@cambara-teste.com.br`) e senha **`trocar_no_setup`** (todos os 5 usuários seed
compartilham essa senha padrão após rodar `seed_auth` — ver limitações de autenticação
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
  analytics.py     lógica das 4 perguntas de negócio da seção 4 do briefing
  geo.py           contorno do Brasil (SVG) + projeção lat/lon para o mapa do dashboard
  services.py      camada de escrita: registrar_venda / registrar_distrato
  nl_assistant.py  assistente de linguagem natural (texto-para-SQL com Gemini)
  views.py / urls.py / forms.py
  templates/negocio/*.html
  templatetags/negocio_extras.py   filtro de template (nome + cidade/UF)
static/img/        logo, monograma e foto de fachada da Cambará (gerados/tratados
                    para este teste -- ver seção de identidade visual)
data_cambara.sqlite3   cópia de trabalho da base fornecida (commitada de propósito,
                        para o avaliador rodar sem precisar copiar o .db original)
```

## Decisões de modelagem e tratamento de dados

A base tem inconsistências de grafia propositais (ex.: `unidades.status` aparece como
`"vendida"`, `"Vendida"`, `"VENDIDA"`). Em vez de reescrever as linhas históricas, a regra
foi: **nunca alterar dados históricos para "corrigir" grafia** — normalizar em Python na
hora da leitura (`negocio/normalize.py`), e escrever sempre com grafia canônica a partir
de agora (`negocio/services.py`). Isso evita perder rastro do que veio "sujo" da origem.

**Achado de qualidade de dados:** toda unidade com status canônico `"cancelado"` tem uma
venda vinculada com status canônico `"distrato"` — ou seja, `"Cancelado"` e `"Distrato"`
são duas grafias históricas diferentes para o mesmo evento (uma venda que caiu e cuja
unidade nunca voltou ao estoque disponível no cadastro). Isso significa que,
historicamente, um distrato **não** devolvia a unidade para "Disponível" na base como
veio. A camada de escrita desta aplicação segue a regra explícita do briefing em vez do
padrão histórico: **todo novo distrato devolve a unidade para "Disponível"**, liberando-a
para uma nova venda.

Verificado também: `unidades.status` e `vendas.status_venda` já são consistentes entre si
uma vez normalizados (nenhuma unidade "vendida" com venda "distrato" e vice-versa) —
então a única inconsistência real de estoque é a de `"cancelado"` acima.

**Achado de qualidade de dados:** 37 das 150 linhas de `vendas` com `data_distrato`
preenchida ainda têm `status_venda` dizendo "ativa" (em alguma grafia) — o sistema de
origem falhou em atualizar esse campo ao registrar o distrato. `data_distrato` é tratado
como a fonte de verdade (`negocio/normalize.py:venda_esta_ativa`): uma venda com data de
distrato preenchida sempre conta como distrato, independente do que `status_venda` diga.
Isso afeta a pergunta 1 (velocidade de vendas) e a listagem de "vendas ativas" na camada
de escrita — sem essa correção, seria possível tentar registrar um segundo distrato numa
venda que, por essa lógica, já não está mais ativa.

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
   e infla o ticket médio por cliente (de ~R$ 3,15 milhões para ~R$ 3,31 milhões nesta
   base) — exatamente a distorção que a pergunta de negócio pede para expor, só que na
   direção oposta da intuição inicial: o risco aqui era criar duplicidade que não existe,
   não deixar passar uma que existe.
4. **Financeiro reportado vs. recalculado**: recalculado = `receita_reconhecida −
   custo_incorrido − despesas_corporativas_rat`; inconsistente quando
   `|recalculado − reportado| > R$ 0,01` (tolerância de arredondamento).

Cada premissa também aparece na própria tela do dashboard, ao lado do resultado.

## Dashboard (tela inicial)

- **Mapa de empreendimentos**: mapa do Brasil (SVG) com um marcador por cidade, tamanho
  proporcional ao número de empreendimentos ali, tooltip com os nomes ao passar o mouse.
  O contorno é o path `brazilMainland` extraído do arquivo *"Brazil location map.svg"*
  (Wikimedia Commons, autor **NordNordWest**, licença
  [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/deed.pt_BR),
  https://commons.wikimedia.org/wiki/File:Brazil_location_map.svg). As coordenadas de cada
  cidade são projetadas para o mesmo espaço do SVG usando a projeção equirretangular e os
  limites geográficos documentados naquele arquivo (`negocio/geo.py:project`).
- **Gráfico 1 — velocidade de vendas**: barras verticais, ordem decrescente da esquerda
  para a direita, as 3 piores em destaque (vermelho).
- **Gráfico 2 — risco de estouro de custo**: barras horizontais, ordem decrescente de cima
  para baixo, destaque para os empreendimentos com estouro acima da média do grupo.
- **Perguntas**: respostas em texto corrido para as perguntas 3 (clientes duplicados) e 4
  (financeiro reportado vs. recalculado) — as que não fazem sentido como gráfico de barras.
  A resposta da pergunta 4 é uma hipótese inicial ainda em revisão (documentado no próprio
  texto da tela).
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

## Autenticação — o que É e o que NÃO é

Login funcional contra a tabela `usuarios` já existente, **sem** `django.contrib.auth`
(decisão deliberada: o briefing pede autenticação simples construída sobre os dados já na
base, não um sistema de produção). Implementação em `negocio/auth.py`:

- Senha comparada como `SHA-256(salt fixo + senha)` contra `usuarios.senha_hash`.
- `manage.py seed_auth` troca o placeholder `"trocar_no_setup"` (que veio na base) pelo
  hash real da mesma string, então a senha de demonstração de todos os usuários seed é
  literalmente `trocar_no_setup`.
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

1. O Gemini recebe o schema das 7 tabelas (com aviso sobre grafia inconsistente e uma
   função SQL customizada `noaccent()` registrada na conexão, para casar nomes/cidades
   mesmo se a pergunta do usuário vier sem acento) e gera **uma única consulta SELECT**.
2. A consulta é validada (só `SELECT`/`WITH`, sem `;`, sem palavras-chave de
   escrita/pragma) e executada numa conexão SQLite **aberta em modo somente-leitura**
   (`?mode=ro`), independente da conexão do Django — mesmo que a validação falhasse, o
   SQLite recusaria a escrita nessa conexão.
3. As linhas retornadas (dados reais) são devolvidas ao Gemini, que é instruído a
   responder **somente com base nelas** e a dizer explicitamente quando a tabela vier
   vazia, em vez de adivinhar.

A tela do assistente sempre mostra o SQL gerado e a tabela de resultados brutos ao lado
da resposta em texto, para o avaliador conferir a resposta contra os dados diretamente.

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

| E-mail | Papel | Senha |
|---|---|---|
| diretoria@cambara-teste.com.br | diretoria | trocar_no_setup |
| comercial@cambara-teste.com.br | comercial | trocar_no_setup |
| engenharia@cambara-teste.com.br | engenharia | trocar_no_setup |
| financeiro@cambara-teste.com.br | financeiro | trocar_no_setup |
| candidato@cambara-teste.com.br | diretoria | trocar_no_setup |
