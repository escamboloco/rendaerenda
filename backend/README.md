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

cp .env.example .env   # preencha DATABASE_URL (Postgres) e REDIS_URL no mínimo

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Para checar sem Postgres/Redis instalados (ex.: sanity check rápido), use `DATABASE_URL=sqlite:///db.sqlite3` + `USE_LOCMEM_CACHE=True` + `CELERY_TASK_ALWAYS_EAGER=True` no `.env` (ou como env var na hora de rodar) — mas produção é sempre Postgres + Redis reais.

**Sempre que mexer em `templates/**/*.html` ou `static/css/input.css`, rode `npm run build:css` de novo antes de commitar** — o build do Render não roda `npm` (ver `build.sh`), então o CSS compilado precisa estar atualizado no repo.

## Apps

| App | Responsabilidade |
|---|---|
| `accounts` | Usuário, verificação de idade (Lei 15.211/2025), KYC de vendedora, formulário de cadastro |
| `stores` | Loja da vendedora, plano de assinatura da loja, onboarding, boost |
| `catalog` | Produtos (itens físicos), imagens, página de produto |
| `subscriptions` | Assinatura mensal obrigatória do comprador, checkout, NF de serviço |
| `payments` | Pedido, checkout, split via PSP (Asaas) amarrado ao CPF do titular, NF de comissão, e-mails de confirmação |
| `wallet` | Saldo (ledger) da vendedora, dashboard, saque — sempre para a chave Pix = CPF da titular, registro de postagem/rastreio |
| `shipping` | Cotação de frete e rastreio via API dos Correios (PAC/SEDEX) |
| `moderation` | Fila de moderação prévia + denúncias (botão em toda página de conteúdo) |
| `offers` | Pedidos personalizados: comprador oferece valor por um item, vendedora aceita/recusa/contrapropõe |
| `core` | Age gate, SEO (sitemap/robots/legal), middleware de segurança, filtro de logs |

## Identidade, CPF e privacidade

- **Idade oficial** vem sempre de `AgeVerification.validated_birth_date` (data retornada pela base oficial do CPF no provider de KYC) — nunca da data digitada no cadastro. Ver `apps/accounts/services.py`.
- **Telefone**: `apps/accounts/phone.py` só envia o OTP por SMS depois de confirmar com um bureau que a linha pertence ao CPF do cadastro (`PHONE_CPF_BUREAU_*`). Compra e assinatura exigem `is_phone_verified=True`.
- **Pagamento**: toda cobrança (pedido, assinatura, plano de loja, boost) é criada em um customer do PSP amarrado ao CPF da conta (`apps/payments/services.py`). Pix pago por CPF diferente é estornado automaticamente no webhook (`verify_payer_cpf`).
- **Saque**: sempre para a chave Pix = CPF da dona da loja — não é configurável (`apps/wallet/services.py`).
- **Apelido/nome social** (`User.public_alias`): usado só na interação comprador↔vendedora (pedidos personalizados). Pagamento, NF, KYC e admin sempre usam a identidade civil.

## Front-end

- Tailwind CSS compilado localmente (`package.json` / `tailwind.config.js` / `static/css/input.css` → `static/css/tailwind.css`), sem CDN — CSP em `config/settings.py` é `script-src 'self'` estrito.
- HTMX e Alpine.js vendorizados em `static/vendor/` (baixados uma vez, sem dependência de terceiros em runtime).
- Componentes JS pequenos ficam inline nos templates (`{% block extra_body %}`); o único script global é `static/js/app.js` (modal de denúncia).
- Design tokens (cor de marca, superfícies, etc.) em `tailwind.config.js`.

## Deploy no Render

Use o `render.yaml` na raiz do repositório (Blueprint). Ele sobe: web (gunicorn), worker Celery (com beat embutido) e Redis. **Postgres não é provisionado pelo blueprint** — o projeto usa um banco premium já existente em produção (o plano `starter` gerenciado pelo blueprint pode não estar disponível na conta); `DATABASE_URL` é preenchido manualmente em cada serviço.

1. Rode `npm run build:css` e commite `static/css/tailwind.css` (o build do Render é Python puro, sem Node — ver `build.sh`).
2. No dashboard do Render, crie o Blueprint apontando pro repositório.
3. Preencha as variáveis marcadas `sync: false` no `render.yaml` (segredos: Asaas, S3, KYC, Correios, SMTP, `SITE_DOMAIN`) — incluindo `DATABASE_URL` de cada serviço, com a **Internal Database URL** do Postgres existente (mais rápida e sem custo de bandwidth do que a External, já que web/worker rodam dentro do próprio Render).
4. Depois do primeiro deploy, rode `python manage.py createsuperuser` via shell do Render.

## Checklist antes de expor a público

Ver `docs/BASE_JURIDICA.md` seção 7 — nenhuma feature entra em produção sem isso.
