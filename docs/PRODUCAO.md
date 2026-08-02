# Checklist de produção — Renda & Renda

Documento operacional: o que precisa estar verdadeiro antes de abrir o site
para o público, e como conferir. O checklist **jurídico** é o da seção 7 de
`BASE_JURIDICA.md` — este aqui é o técnico, e um não substitui o outro.

---

## 1. Bloqueadores (o site não abre sem isso)

| # | Item | Como conferir |
|---|---|---|
| 1 | `DJANGO_SECRET_KEY` gerado pelo Render (nunca reaproveitado de dev) | Painel → Environment |
| 2 | `DJANGO_DEBUG=False` | `curl -I https://rendaerenda.com.br/` não pode vazer stack trace |
| 3 | `ASAAS_API_KEY` de produção, com o nicho aprovado por escrito pelo Asaas | E-mail/contrato arquivado |
| 4 | `ASAAS_WEBHOOK_TOKEN` definido **e** cadastrado no painel do Asaas | `GET /webhooks/asaas/` responde 200; `POST` sem token responde 403 |
| 5 | Webhook do Asaas apontando para `https://rendaerenda.com.br/webhooks/asaas/` | Painel Asaas → Integrações |
| 6 | SMTP real (`EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`) | Sem isso os e-mails caem no log e ninguém recebe o link do pedido |
| 7 | Toda loja ativa com `pix_key` preenchida | Admin → Lojas; sem chave o repasse não sai |
| 8 | Cron `expire-orders` rodando | Render → Cron → último run OK. Sem ele, carrinho abandonado tira peça única do ar para sempre |
| 9 | Crons `release-deliveries` e `release-escrow` rodando | Sem eles o dinheiro fica preso na custódia e a vendedora nunca recebe |
| 10 | `manage.py createcachetable` executado | Sem a tabela, o rate limit quebra |
| 11 | `SEED_PAYMENT_TEST` | `True` povoa 20+ lojas / 70+ produtos (seed_demo) no deploy; `False` limpa demo antes de abrir ao público |
| 12 | SuperFrete em produção (token + saldo + sandbox off) | Ver seção 8 abaixo; `manage.py check_superfrete` |

## 2. Teste de fumaça (fazer com dinheiro real, valor baixo)

Com `SEED_PAYMENT_TEST=True`, use qualquer loja demo (ex. `/loja/atelie-da-luna/`)
com preços e CEPs variados para validar frete/checkout. Antes de abrir ao
público amplo, mude para `False` e faça redeploy (o build limpa o demo).

1. Abrir o site anônimo → confirmar age gate.
2. Adicionar item à sacola (com um adicional, se houver) → `/finalizar/`.
3. Preencher dados de guest + CEP (o endereço deve autopreencher).
4. Gerar o Pix → **conferir se o QR aparece**.
5. Pagar de uma conta com **o mesmo CPF** informado.
6. A tela deve confirmar sozinha em até ~10s (polling), sem recarregar.
7. Conferir:
   - pedido `paid` no admin;
   - `WalletEntry` de crédito criado **uma vez** e **retido** (`available_at` no futuro);
   - `Order.payout_sent_at` ainda vazio — a vendedora não pode ter recebido;
   - e-mail de confirmação recebido;
   - estoque do item zerado e fora da vitrine.
8. Repetir o webhook manualmente (reenviar pelo painel do Asaas) e conferir
   que **não** aparece um segundo crédito.
9. Na página do pedido, clicar em "Recebi, liberar pagamento" e conferir:
   - `WithdrawalRequest` com `provider_transfer_id` (o Pix saiu);
   - `Order.payout_sent_at` preenchido;
   - clicar de novo devolve 409, sem segundo Pix.
10. Repetir com um anúncio digital: o checkout não deve pedir endereço e o
    arquivo tem que abrir na página do pedido só depois do pagamento.
11. Criar um pedido e não pagar → rodar `manage.py expire_orders` → o item
    volta para a vitrine.
12. Abrir uma contestação em outro pedido e conferir que `release_escrow`
    **não** repassa o valor.
13. Com SuperFrete ligado: no checkout o frete deve listar PAC/SEDEX (não
    tarifa fixa). Depois do Pix, o `Shipment` precisa ter `label_url` e a
    vendedora recebe o e-mail com o PDF.

## 3. Pagamento por CPF divergente

Com `REFUND_ON_PAYER_CPF_MISMATCH=True` (padrão), Pix pago de um CPF
diferente do titular do pedido é **estornado automaticamente** e o item volta
para a vitrine. Isso é uma trava de idade, não antifraude — mas gera atrito
real (marido pagando a compra da esposa, por exemplo).

Antes de abrir para volume, decida:
- manter `True` (mais seguro juridicamente, mais estorno); ou
- `False` + revisão manual da fila de `payer_cpf_matched=False` no admin.

## 4. O que ainda está pendente (não bloqueia o soft-launch)

| Item | Situação | Risco de deixar assim |
|---|---|---|
| Verificação biométrica de idade | Código pronto, provider **não contratado** | O age gate é só declaratório. É a maior dívida legal do projeto (Lei 15.211/2025) |
| KYC de vendedora (`REQUIRE_SELLER_KYC=False`) | Desligado no soft-launch | Qualquer conta abre loja |
| Verificação de telefone (bureau + SMS) | Sem provider configurado | Pedido personalizado exige `is_phone_verified`, então fica bloqueado na prática |
| NFS-e (`NFSE_PROVIDER_API_KEY`) | Não configurada; a task pula sem erro | Comissão sem nota fiscal |
| Cotação de frete real | Ver seção 8 (go-live SuperFrete) | Sem token, cai na tarifa fixa; sem saldo a etiqueta não é liberada |
| Remetente discreto | `SHIPPING_SENDER_NAME` + `SHIPPING_SENDER_DOCUMENT` (CNPJ) | Sem isso, usa `PLATFORM_LEGAL_NAME` / `SITE_NAME` |
| Etiqueta pré-paga | `PLATFORM_BUYS_SHIPPING_LABEL=True` (já no `render.yaml`) | Vendedora só imprime PDF na carteira / e-mail |
| Cartão de crédito | Funciona pela página hospedada do Asaas (sem formulário no site) | Um passo a mais que o Pix; parcelamento fica nas mãos do Asaas |
| Boost de loja | `StoreBoostPurchaseView` cria o boost sem cobrar | Receita não realizada — desative a compra ou implemente a cobrança |
| Mídia em disco do Render | `/var/data` com 5 GB | Disco cheio derruba upload; migrar para S3 antes de escalar |
| Anexo no chat do pedido | Só texto | Comprovante de postagem tem que ir por e-mail |
| Moderação de anúncio | Fila existe, aprovação é manual no admin | Sem revisor ativo, anúncio novo não vai ao ar |

## 5. Ligando a verificação biométrica de idade

O código está pronto e desligado por falta de contrato. Para ativar:

1. Contrate um bureau (idwall, Unico, CAF, Serpro Datavalid) declarando o
   nicho — o mesmo cuidado do PSP.
2. Preencha no ambiente:
   - `AGE_KYC_PROVIDER` — nome do bureau (só rotula o registro);
   - `AGE_KYC_API_URL` — **endpoint exato do contrato**. Não é derivado do
     nome do provider de propósito: cada bureau tem rota e payload próprios;
   - `AGE_KYC_API_KEY` — chave do contrato, que também autentica o webhook.
3. Configure o callback do bureau para `https://rendaerenda.com.br/webhooks/kyc/`
   com o header `X-Kyc-Webhook-Token` = `AGE_KYC_API_KEY`.
4. Confira que o payload do bureau bate com o esperado em
   `apps/accounts/services.apply_verification_result`: `reference_id`,
   `approved`, `document_validated` e `birth_date`. Se o formato for outro,
   adapte **só essa função** — o resto do fluxo não muda.
5. Ligue `REQUIRE_SELLER_KYC=True` para exigir aprovação antes de abrir loja.

Enquanto estiver desligado: `POST /api/verificacao-idade/` responde 503 e o
webhook responde 503 — ninguém é aprovado por engano. A idade oficial sempre
vem de `validated_birth_date` (base do CPF), nunca da data digitada, e menor
confirmado é banido na hora.

## 6. Resolvendo uma disputa

O comprador contesta pela página do pedido; o valor fica travado na custódia.
Para fechar o caso, no **admin → Pedidos**, selecione o pedido e use uma das
duas ações:

- **Disputa procedente: estornar para o comprador** — pede o estorno ao Asaas,
  desfaz o crédito da vendedora e devolve o item para a vitrine.
- **Disputa improcedente: liberar o valor para a vendedora** — tira da custódia
  e dispara o Pix.

Se o estorno acontecer **depois** de o Pix já ter saído (caso raro: liberação
automática antes da contestação), o ajuste deixa o saldo da loja negativo de
propósito e um ERROR vai para o log — recuperar o valor é ação humana.

## 7. Monitoramento mínimo

- Render → Logs: procurar por `Falha no repasse`, `Falha no Pix automatico`,
  `Asaas` com nível ERROR.
- Admin → Pedidos com `status=awaiting_payment` e `expires_at` no passado:
  se acumular, o cron `expire-orders` parou.
- Admin → `WithdrawalRequest` com `status=failed`: repasse que não saiu,
  precisa de Pix manual pelo painel do Asaas.
- Logs SuperFrete: `SuperFrete recusou`, `etiqueta` / `buy_label_for_order`.
  Cron `poll-shipments` precisa rodar de hora em hora para o rastreio.

## 8. Go-live SuperFrete (produção)

O código já usa SuperFrete (`SHIPPING_PROVIDER=superfrete`). Falta só
credencial e saldo reais no Render.

### Painel SuperFrete
1. Conta em [web.superfrete.com](https://web.superfrete.com) (produção — **não** sandbox).
2. **Integrar → Desenvolvedores → Confirmar** e copiar o token.
3. Recarregar saldo (Pix) — sem saldo a cotação funciona, mas
   `POST /api/v1/orders/finalize` falha e a vendedora não recebe o PDF.
4. Conferir serviços ativos (PAC=1, SEDEX=2, Mini Envios=17, Jadlog=3).

Docs: [primeiros passos](https://superfrete.readme.io/reference/primeiros-passos).

### Variáveis no Render (Environment Group `rendaerenda-shared` + Web)

| Variável | Valor produção |
|---|---|
| `SHIPPING_PROVIDER` | `superfrete` (já no blueprint) |
| `SUPERFRETE_SANDBOX` | `False` (já no blueprint) |
| `SUPERFRETE_TOKEN` | token de **produção** (sync:false — preencher à mão) |
| `SUPERFRETE_SERVICES` | `1,2,17,3` |
| `SUPERFRETE_USER_AGENT` | `Renda & Renda/1.0 (suporte@rendaerenda.com.br)` |
| `PLATFORM_BUYS_SHIPPING_LABEL` | `True` |
| `CHECKOUT_FREE_SHIPPING` | `False` |
| `SHIPPING_SENDER_NAME` | razão social / nome neutro na etiqueta |
| `SHIPPING_SENDER_DOCUMENT` | CNPJ da plataforma |
| `SHIPPING_SENDER_EMAIL` | `suporte@rendaerenda.com.br` |
| `SHIPPING_SENDER_PHONE` | telefone com DDD |

O token precisa existir **também** no cron `rendaerenda-poll-shipments`
(já declarado no `render.yaml`).

### Depois de salvar as env vars
1. **Manual Deploy** do serviço web (e do cron de shipments, se não herdar).
2. No Shell do Render (web):
   ```bash
   python manage.py check_superfrete
   ```
   Tem que listar opções PAC/SEDEX/etc. Se reclamar de sandbox ou token, a
   variável não entrou — confira o Environment Group.
3. Admin → Lojas: toda loja ativa precisa de CEP **e** rua/número/bairro/cidade/UF
   de postagem (campos privados `origin_*`). Lojas antigas sem isso bloqueiam
   a compra da etiqueta.
4. Pedido real de valor baixo → pagar → conferir:
   - `Shipment.shipping_provider=superfrete`
   - `provider_order_id` preenchido
   - `label_url` com PDF
   - e-mail `label_ready` para a vendedora
5. Após postagem, o cron `poll_shipments` atualiza o rastreio sozinho.

### Não misturar ambientes
- Token de sandbox **não** funciona em `api.superfrete.com`.
- Com `SUPERFRETE_SANDBOX=True` as etiquetas **não** são válidas para postagem.
- Remova qualquer `MELHOR_ENVIO_*` antigo do painel — não é mais lido.

## 9. Envs pendentes — o que preencher e como

Onde: Render → Environment Group `rendaerenda-shared` (a maioria) e
serviço `rendaerenda-web` (Asaas/token). Depois de salvar → **Manual Deploy**.

### Já pode ligar sem CNPJ

| Variável | Onde | Valor / como gerar | Se ficar vazio |
|---|---|---|---|
| `ASAAS_WEBHOOK_TOKEN` | Web | Gere um segredo: `openssl rand -hex 32` | Webhook responde **503** — Pix pago **não** confirma sozinho |
| `CHECKOUT_FREE_SHIPPING` | Shared | `False` (já no blueprint) | Se `True`, frete R$ 0 e sem cotação |
| `MODERATION_ALERT_EMAIL` | Shared | Caixa que **você** lê (ex.: `moderacao@rendaerenda.com.br` ou Gmail pessoal) | Contestação só vai pro log — ninguém é avisado |
| `STATEMENT_DESCRIPTOR` | Shared | Nome neutro curto, até ~22 chars (ex.: `RR COMERCIO` ou a razão social) | Checkout não mostra a linha “no extrato aparece …” |

#### `ASAAS_WEBHOOK_TOKEN` — passo a passo
1. No seu computador:
   ```bash
   openssl rand -hex 32
   ```
2. Cole o resultado em Render → `rendaerenda-web` → `ASAAS_WEBHOOK_TOKEN`.
3. Asaas → Integrações → Webhooks (ou criar webhook):
   - URL: `https://rendaerenda.com.br/webhooks/asaas/`
   - Token / `asaas-access-token`: **o mesmo valor**
   - Eventos: `PAYMENT_RECEIVED`, `PAYMENT_CONFIRMED`, `PAYMENT_REFUNDED`,
     `PAYMENT_CHARGEBACK_REQUESTED`, `PAYMENT_OVERDUE`
4. Conferir:
   ```bash
   curl -s https://rendaerenda.com.br/webhooks/asaas/
   # {"ok": true, "service": "asaas-webhook", ...}
   ```
5. Redeploy do web. Sem o token no Render **e** no painel Asaas, o pedido
   fica `awaiting_payment` mesmo depois do Pix.

#### `CHECKOUT_FREE_SHIPPING`
Confirme no painel que está `False` (string). Blueprint já manda isso; se o
serviço foi criado antes, o valor antigo pode ter ficado — edite à mão.

#### `MODERATION_ALERT_EMAIL`
Use um e-mail que chega no celular. SMTP (`EMAIL_HOST` / USER / PASSWORD)
precisa estar ok, senão o alerta também não sai.

#### `STATEMENT_DESCRIPTOR`
É **só copy no checkout**. O nome que aparece no extrato do cartão/Pix é o
da **conta Asaas** (e, com CNPJ, a razão social neutra). Escolha algo genérico
tipo comércio/marketplace — nunca o nicho adulto.

### Depende do CNPJ (etiqueta + identidade legal)

Sem CNPJ a plataforma ainda vende (Asaas `pf` + SuperFrete), mas a etiqueta
fica frágil e a cobrança discreta no extrato não fecha de verdade.

| Variável | Valor quando o CNPJ existir |
|---|---|
| `PLATFORM_LEGAL_NAME` | Razão social **neutra** do cartão CNPJ |
| `PLATFORM_CNPJ` | Só dígitos, 14 chars (ex.: `12345678000199`) |
| `SHIPPING_SENDER_NAME` | Mesma razão social (ou nome fantasia neutro) — **não** “Renda & Renda” se for explícito demais no pacote |
| `SHIPPING_SENDER_DOCUMENT` | Mesmo CNPJ (só dígitos) |
| `SHIPPING_SENDER_EMAIL` | `suporte@rendaerenda.com.br` (já no blueprint) |
| `SHIPPING_SENDER_PHONE` | Celular/WhatsApp com DDD, só dígitos (ex.: `11999998888`) |

**Não precisa** preencher `SHIPPING_SENDER_STREET/NUMBER/DISTRICT/CITY/STATE`
se cada loja tiver o endereço de postagem (`origin_*`) — a etiqueta usa o
endereço da vendedora e o **nome/CNPJ da plataforma**.

#### Enquanto o CNPJ não sai
1. Deixe `SHIPPING_SENDER_*` / `PLATFORM_CNPJ` vazios **ou**
2. Temporário (só para testar etiqueta): `SHIPPING_SENDER_NAME` = nome civil
   completo do titular PF + `SHIPPING_SENDER_DOCUMENT` = CPF (11 dígitos) +
   telefone. A SuperFrete aceita documento; o remetente deixa de ser neutro.
3. Priorize abrir o CNPJ com razão social neutra (`docs/BASE_JURIDICA.md`)
   e aí troque para CNPJ + `ASAAS_ACCOUNT_TYPE=pj` quando for usar split.

### Checklist rápido no Render depois de preencher
- [ ] `ASAAS_WEBHOOK_TOKEN` no web **igual** ao token do webhook Asaas  
- [ ] `CHECKOUT_FREE_SHIPPING=False`  
- [ ] `MODERATION_ALERT_EMAIL` com caixa real  
- [ ] `STATEMENT_DESCRIPTOR` neutro  
- [ ] Com CNPJ: `PLATFORM_*` + `SHIPPING_SENDER_NAME/DOCUMENT/PHONE`  
- [ ] Manual Deploy → `curl` no webhook → `python manage.py check_superfrete`

## 10. Primeiro acesso ao painel de gestão

O painel operacional fica em `https://rendaerenda.com.br/gestao/entrar/`.
No serviço **web** do Render, preencha as quatro variáveis juntas:

| Variável | Valor |
|---|---|
| `ADMIN_EMAIL` | e-mail exclusivo da pessoa administradora |
| `ADMIN_PASSWORD` | senha aleatória com pelo menos 12 caracteres |
| `ADMIN_CPF` | CPF da administradora, somente 11 dígitos |
| `ADMIN_BIRTH_DATE` | nascimento no formato `AAAA-MM-DD` |

Para gerar uma senha forte:

```bash
openssl rand -base64 32
```

O build executa `python manage.py create_admin`. Na primeira execução ele
cria a conta; nos próximos deploys apenas confirma as permissões e **não**
redefine a senha. Para trocar a senha deliberadamente, abra o Shell do web:

```bash
python manage.py create_admin --reset-password
```

Nesse comando, `ADMIN_PASSWORD` deve conter temporariamente a nova senha.
Depois do acesso, prefira alterar a senha pelo Django Admin e remova
`ADMIN_PASSWORD`, `ADMIN_CPF` e `ADMIN_BIRTH_DATE` do Render; mantenha somente
`ADMIN_EMAIL`. Nos deploys seguintes, o comando apenas confirma as permissões
da conta existente. Qualquer outra combinação parcial falha de propósito.

O painel tem visão geral, pedidos, financeiro, lojas (melhores avaliações
primeiro), moderação, denúncias, disputas e contas. O `/admin/` permanece para
KYC e alterações técnicas profundas.
