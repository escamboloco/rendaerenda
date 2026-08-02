# Renda & Renda — backend

Django 5 + DRF + templates (HTMX + Alpine.js + Tailwind compilado
localmente). Ver `/docs/BASE_JURIDICA.md` (raiz do repo) para as regras de
compliance que todo código aqui precisa respeitar.

## Rodando localmente

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

npm install
npm run build:css   # gera static/css/tailwind.css a partir de static/css/input.css

cp .env.example .env   # preencha DATABASE_URL (Postgres) no mínimo

python manage.py migrate
python manage.py createcachetable   # tabela do cache (rate-limit) - sem Redis
python manage.py createsuperuser
python manage.py runserver
```

Sem Redis nem worker Celery: cache e rate-limit usam uma tabela no próprio
Postgres (`django.core.cache.backends.db.DatabaseCache`), e toda task Celery
roda síncrona no mesmo processo (`CELERY_TASK_ALWAYS_EAGER = True` sempre,
ver `config/settings.py`) — arquitetura de menor custo no Render. Para checar
sem Postgres instalado, use `DATABASE_URL=sqlite:///db.sqlite3` +
`USE_LOCMEM_CACHE=True` — mas produção é sempre Postgres real.

**Sempre que mexer em `templates/**/*.html` ou `static/css/input.css`, rode `npm run build:css` de novo antes de commitar** — o build do Render não roda `npm` (ver `build.sh`), então o CSS compilado precisa estar atualizado no repo.

## Testes

```bash
DJANGO_SECRET_KEY=test DJANGO_DEBUG=True DATABASE_URL=sqlite:///test.sqlite3 USE_LOCMEM_CACHE=True python manage.py test tests
```

A suíte em `tests/` cobre o caminho do dinheiro: preço/comissão, reserva de
estoque, oversell, expiração de pedido, idempotência do webhook (repasse
nunca sai duas vezes), estorno por CPF divergente, polling de status,
sacola e age gate. **Nenhum teste toca a rede** — o provider de pagamento é
substituído por um dublê em `tests/factories.py`. Se um teste começar a
chamar o Asaas de verdade, é sinal de que alguém importou
`get_payment_provider` direto em vez de chamar `services.get_payment_provider()`.

## Apps

| App | Responsabilidade |
|---|---|
| `accounts` | Usuário, verificação de idade (Lei 15.211/2025), KYC de vendedora, formulário de cadastro |
| `stores` | Loja da vendedora, vitrine, ranking, onboarding, boost |
| `catalog` | Produtos (itens físicos), imagens, página de produto |
| `subscriptions` | Assinatura opcional do comprador, checkout, NF de serviço |
| `payments` | Pedido, checkout, integração Asaas, webhook, NF de comissão, e-mails |
| `wallet` | Ledger da vendedora, dashboard, saque/repasse Pix |
| `shipping` | Cotação de frete e rastreio (Correios / SuperFrete) |
| `moderation` | Fila de moderação prévia + denúncias |
| `offers` | Pedidos personalizados |
| `core` | Age gate, SEO, consulta de CEP, middleware de segurança, filtro de logs |

### Como o app de pagamentos está organizado

```
apps/payments/
  asaas.py      HTTP puro com o Asaas: timeout, erro traduzido, sem regra de negócio
  services.py   Tradução domínio <-> PSP (comissão, split, repasse, CPF do pagador)
  checkout.py   Regra de negócio: reservar estoque, cobrar, confirmar, expirar
  views.py      HTTP: API de checkout, sacola, status do pedido, webhook
```

Regra de ouro: **nenhuma chamada de rede dentro de transação de banco.**
`reserve_order()` trava o estoque numa transação curta; a cobrança no Asaas
acontece depois. Se o Asaas falhar, o pedido é cancelado e o estoque volta.

## Modelo de negócio

Marketplace +18 de **itens** e **conteúdo** — nunca de serviço presencial.

| Peça | Como funciona |
|---|---|
| Comissão | `PLATFORM_COMMISSION_PERCENT` (15% por padrão) **por cima** do valor que a vendedora pediu. Ela recebe o líquido inteiro; quem compra paga a diferença |
| Custódia | O Pix fica com a plataforma. A vendedora só saca depois que o comprador confirma o recebimento (ou depois do prazo) |
| Disputa | `DISPUTE_WINDOW_DAYS` (7) para contestar. Contestou, o valor trava até a moderação decidir |
| Mensalidade | Nenhuma. Abrir loja e anunciar é grátis |
| Tipos de anúncio | `physical` (correio), `digital` (arquivo entregue pelo site), `custom` (sob encomenda) |
| Adicionais | `ProductAddon` — extras pagos escolhidos no anúncio, cobrados no mesmo pedido, com a mesma regra de comissão |
| Frete | Cotado CEP loja → CEP comprador. Plataforma compra etiqueta SuperFrete (remetente neutro); embalagem neutra vai para a vendedora. `CHECKOUT_FREE_SHIPPING=True` zera no soft-launch |

## Fluxo de uma compra

1. A pessoa monta a sacola (localStorage guarda só `id`, quantidade e
   adicionais escolhidos).
2. `/finalizar/` recalcula tudo no servidor (`POST /api/sacola/`) — preço
   nunca vem do navegador.
3. `POST /api/checkout/` reserva o estoque, cria a cobrança Pix e devolve
   QR + copia-e-cola + link de acompanhamento. Sacola só de conteúdo
   digital pula endereço e frete.
4. A tela consulta `GET /api/pedido/<token>/status/` a cada 4s. Esse endpoint
   **consulta o Asaas diretamente**, então a compra confirma mesmo se o
   webhook não estiver configurado ou falhar.
5. `POST /webhooks/asaas/` confirma em background (caminho normal).
6. Confirmado: crédito **retido** no ledger + e-mails. Conteúdo digital
   já fica disponível na página do pedido.
7. `POST /api/pedido/<token>/confirmar/` (o botão "recebi") libera a
   custódia e dispara o Pix para a vendedora. Sem resposta, os crons
   `release_deliveries` / `release_escrow` liberam no prazo.
8. Não pagou até `expires_at`? `manage.py expire_orders` devolve o item
   para a vitrine.

Tudo idempotente: webhook repetido não credita duas vezes e
`Order.payout_sent_at` impede repasse duplicado.

## Páginas públicas

| Rota | O que é |
|---|---|
| `/` | Vitrine: destaques, mais vendidos, categorias, provas de segurança |
| `/anuncios/` | Catálogo completo com filtros (tipo, categoria, ordenação) |
| `/categorias/` | Índice de categorias + o que não é permitido |
| `/como-funciona/` | Explicação da custódia, prazos e privacidade |
| `/vender/` | Landing de captação de vendedoras |
| `/loja/<slug>/` | Loja da vendedora |
| `/loja/<slug>/item/<slug>/` | Anúncio: galeria, adicionais, perguntas, reputação |
| `/finalizar/` | Funil de checkout em 3 passos |
| `/pedido/<token>/` | Pedido: Pix, status ao vivo, download digital, confirmar/contestar |

## Integração Asaas — passo a passo

1. Conta Asaas aprovada **com o nicho declarado por escrito**
   (vestuário íntimo usado entre pessoas físicas — ver `docs/BASE_JURIDICA.md` § 5).
2. `ASAAS_API_KEY` = chave de produção (ou sandbox + `ASAAS_API_URL=https://api-sandbox.asaas.com/v3`).
3. `ASAAS_WEBHOOK_TOKEN` = um segredo forte gerado por você.
   **Sem essa variável o webhook responde 503 de propósito** — endpoint
   aberto deixaria qualquer um marcar pedido como pago.
4. No painel do Asaas → Integrações → Webhooks:
   - URL: `https://rendaerenda.com.br/webhooks/asaas/`
   - Token de autenticação: o mesmo `ASAAS_WEBHOOK_TOKEN`
   - Eventos: `PAYMENT_RECEIVED`, `PAYMENT_CONFIRMED`, `PAYMENT_REFUNDED`,
     `PAYMENT_CHARGEBACK_REQUESTED`, `PAYMENT_OVERDUE`
5. `ASAAS_ACCOUNT_TYPE`: `pf` (cobra tudo e repassa por Pix) ou `pj`
   (subconta por vendedora + split nativo). Só troque para `pj` quando as
   subcontas existirem.
6. Cada loja precisa de `pix_key` cadastrada — é para lá que vai o repasse.

Smoke test interno (nunca com o site aberto): `SEED_PAYMENT_TEST=True`
cria uma loja com 3 itens de R$ 5 (`manage.py seed_payment_test`). Com
`SEED_PAYMENT_TEST=False` (padrão de produção), o `build.sh` executa
`purge_demo_and_test_data --force` e remove lojas/produtos/contas de demo
e teste.

## Identidade, CPF e privacidade

- **Idade oficial** vem sempre de `AgeVerification.validated_birth_date` — nunca da data digitada. Ver `apps/accounts/services.py`.
- **Telefone**: `apps/accounts/phone.py` só envia OTP depois de o bureau confirmar que a linha pertence ao CPF.
- **Pagamento**: cobrança amarrada a um customer do PSP com o CPF do titular. Pix pago por CPF diferente é estornado (`REFUND_ON_PAYER_CPF_MISMATCH`).
- **Saque/repasse**: para a chave Pix cadastrada pela dona da loja.
- **Apelido** (`User.public_alias`): só na interação comprador↔vendedora. Pagamento, NF, KYC e admin usam identidade civil.
- **CEP**: a consulta ao ViaCEP sai do servidor (`/api/cep/<cep>/`), nunca do navegador — mantém a CSP fechada e não expõe o IP da compradora.

## Front-end

- Tailwind compilado localmente, sem CDN — CSP `script-src 'self' 'unsafe-eval'` (o `unsafe-eval` é exigido pelo build padrão do Alpine).
- HTMX e Alpine vendorizados em `static/vendor/`.
- `static/js/app.js` concentra a sacola (`Alpine.store('cart')`), o funil de
  checkout, o polling do pedido, a galeria e os modais.
- `templates/catalog/_product_card.html` é o card reutilizado na vitrine, na
  loja e nos relacionados.

## Deploy no Render

Blueprint em `render.yaml` (raiz do repo). Sobe Postgres + web + 4 crons:

| Cron | Frequência | Para quê |
|---|---|---|
| `expire-orders` | */10 | Confere Pix pendente no Asaas e devolve estoque de pedido não pago |
| `poll-shipments` | 1×/h | Rastreio |
| `release-deliveries` | */30 | Liberação de saldo pós-entrega |
| `marketing-digest` | seg 14h UTC | Newsletter opt-in |

1. `npm run build:css` e commite `static/css/tailwind.css`.
2. Push → Render → **New → Blueprint**.
3. Preencha as variáveis `sync: false` (Asaas, SuperFrete, SMTP, Pix de teste).
4. DNS na Hostinger: `A @ → 216.24.57.1`, `CNAME www → rendaerenda-web.onrender.com`, sem `AAAA`.
5. Shell do web → `python manage.py createsuperuser`.
6. Configure o webhook do Asaas (seção acima).

## Checklist antes de expor a público

Ver `docs/BASE_JURIDICA.md` seção 7 e `docs/PRODUCAO.md` (checklist operacional).
