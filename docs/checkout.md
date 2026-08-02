# Checkout, pagamento, frete e liberação — Renda & Renda

> **Atualização (jul/2026): o modelo mudou para pagamento em custódia.**
> A seção 1 abaixo descreve o modelo anterior (repasse Pix imediato na
> confirmação do pagamento). Hoje o valor fica retido com a plataforma e
> só é repassado quando o comprador confirma o recebimento — ou quando o
> prazo vence sem contestação. A comissão padrão passou de 20% para 15%,
> e o catálogo aceita conteúdo digital e adicionais pagos.
> A referência atual do fluxo é `backend/README.md`
> (seções "Modelo de negócio" e "Fluxo de uma compra") e o checklist
> operacional é `docs/PRODUCAO.md`. O resto deste documento (pesquisa de
> PSP, logística e fiscal) continua valendo.

> Documento técnico + pesquisa. Consolida as decisões do novo modelo de
> negócio e o passo a passo de integração. Como todo o resto do projeto,
> **nada entra em produção sem o aval jurídico** de `docs/BASE_JURIDICA.md`
> (seção 7). As pesquisas abaixo são de julho/2026 — confirme preços,
> contratos e termos de cada fornecedor antes de assinar.

---

## 1. Novo modelo de negócio (o que mudou)

| Antes | Agora |
|---|---|
| Comprador precisava de conta + telefone | **Compra guest** — nome, e-mail, CPF, nascimento (+18), endereço e pagamento |
| Frete repassado à vendedora | **Etiqueta pré-paga** pela plataforma (SuperFrete); embalagem neutra creditada à vendedora |
| Comissão 30% | **~20%** por cima do payout; transportadora fica com a plataforma para a etiqueta |
| Saque manual / retido | **Custódia do item** + Pix da embalagem na confirmação; item libera na entrega |

### Exemplo de cálculo

```
Vendedora quer receber:  R$ 100,00   (payout_amount)
Comissão da plataforma:  R$  20,00   (20% por cima)
─────────────────────────────────
Preço do anúncio:        R$ 120,00   (price)
+ Frete transportadora:  R$  18,00   ← compra a etiqueta (plataforma)
+ Embalagem neutra:      R$   4,50   ← creditada à vendedora
─────────────────────────────────
Comprador paga:          R$ 142,50
Vendedora recebe:        R$ 104,50   (100 + embalagem; item em custódia)
Etiqueta:                já paga — PDF no e-mail / carteira
```

O site **não vende nada** — só conecta comprador e vendedora (Termos de Uso).


---

## 2. Gateway de pagamento — recomendação

### O problema do nicho
Gateways mainstream (Mercado Pago, PagSeguro, Stripe, bancos) **proíbem
conteúdo adulto/íntimo nos termos** — risco de congelar saldo e banir a
conta (`docs/BASE_JURIDICA.md` § 5). **Nunca integrar escondendo o nicho.**
O enquadramento correto aqui é **venda de vestuário íntimo usado entre
pessoas físicas** (produto físico), não conteúdo adulto digital — mas isso
precisa estar **aprovado por escrito** no contrato do PSP.

### Recomendação: Asaas (com Conta Escrow + Split + Subcontas)
Pesquisa (jul/2026) mostrou que o Asaas é o que melhor cobre os 3 requisitos
que o nosso fluxo exige **de forma nativa e em BRL**:

1. **Split de pagamento** — divide automaticamente entre a subconta da
   vendedora e a conta master da plataforma, por transação. (Iugu, Pagar.me
   e Zoop também fazem split; escolhemos Asaas pelo escrow nativo.)
2. **Subconta por vendedora** — criada no onboarding; é ela que recebe o
   repasse, então **a plataforma nunca custodia o dinheiro** (peça central
   da tese jurídica).
3. **Conta Escrow** — retém o valor e libera **por prazo (até 45 dias) ou
   manualmente via API** quando a entrega é confirmada. É exatamente o
   "segura o dinheiro até o comprador confirmar" que queremos.
   - Custo (jul/2026): **R$ 99,90/mês** (conta principal) + **R$ 9,90 por
     subconta** com escrow ativo. Avaliar no volume — pode compensar ligar
     escrow só acima de um ticket mínimo.

**Alternativa**: Iugu (split + subcontas, bom painel de vendedor), mas o
escrow condicionado a evento é menos explícito na doc — exigiria a gente
controlar a retenção pelo lado de cá.

### Meios de pagamento
- **Pix** primeiro (sem chargeback; ideal pro nicho). Já temos a trava de
  **pagamento só pelo CPF do titular** (`apps/payments/services.py:verify_payer_cpf`).
- **Cartão de crédito** como secundário — o Asaas valida titularidade pelo
  `creditCardHolderInfo.cpfCnpj` contra o customer (que é o CPF da conta).

Fontes: [Asaas — Split](https://docs.asaas.com/docs/split-de-pagamentos) ·
[Asaas — Conta Escrow](https://docs.asaas.com/docs/introducao-conta-escrow) ·
[Iugu — Split](https://www.iugu.com/split-pagamentos)

### Split Payment tributário (Reforma / IBS-CBS) — pode usar já?
**Ainda não como fonte única.** Pesquisa (jul/2026):
- A Receita + Comitê Gestor do IBS **publicaram a documentação técnica** da
  Plataforma Pública do Split Payment em junho/2026.
- **2026 é ano de teste** operacional, com alíquota simbólica de 1%.
- A vigência efetiva começa em **2027** (CBS) e o IBS entra progressivamente
  até **2032**. No início vale só para **Pix, boleto e transferência**
  (cartão fica para depois).

**O que isso significa pra nós:** o "split tributário" do governo (separar
CBS/IBS na hora do pagamento) é **diferente** do split comercial do PSP
(dividir entre vendedora e plataforma) que já usamos. Eles vão **coexistir**:
o PSP continua fazendo o split comercial; quando o split tributário virar
obrigatório, o próprio PSP (Asaas/Iugu) fará a segregação do imposto — não é
algo que a gente implementa na mão. **Ação agora:** manter emissão de NFS-e
correta (já temos, `apps/payments/invoicing.py`) e acompanhar o PSP liberar
o suporte. Não bloquear o lançamento por causa disso.

Fontes: [gov.br — documentação técnica](https://www.gov.br/fazenda/pt-br/assuntos/noticias/2026/junho/receita-federal-e-comite-gestor-do-ibs-publicam-documentacao-tecnica-da-plataforma-publica-do-split-payment) ·
[Thomson Reuters](https://www.thomsonreuters.com.br/pt/tax-accounting/onesource-mastersaf/blog/split-payment-reforma-tributaria.html)

---

## 3. Logística — SuperFrete

### Integração adotada
A SuperFrete oferece cotação, emissão e rastreio por API para sites próprios:

- **Cotação simultânea** de PAC, SEDEX, Mini Envios e Jadlog em
  `POST /api/v0/calculator`; Loggi é habilitada nas configurações do token.
- **Etiqueta pré-paga** criada em `POST /api/v0/cart` e paga com o saldo da
  conta em `POST /api/v1/orders/finalize`.
- **PDF e rastreio** consultados em `GET /api/v0/order/info/{id}`.
- **Sandbox separado de produção**; o token e o saldo também são separados.

Implementado em `apps/shipping/superfrete.py` e plugado via
`SHIPPING_PROVIDER=superfrete` (Correios/CWS continua como alternativa).

Fontes oficiais, consultadas em 02/08/2026:
[primeiros passos](https://superfrete.readme.io/reference/primeiros-passos) ·
[cotação](https://superfrete.readme.io/reference/calculator) ·
[etiquetas](https://superfrete.readme.io/reference/etiquetas).

### Fluxo automatizado da etiqueta (já implementado)
1. Comprador escolhe o frete no checkout (cotado do **CEP da vendedora**).
   A embalagem (`PACKAGING_FEE`) já vem somada.
2. Pagamento confirma → webhook do PSP dispara
   `apps.shipping.tasks.buy_label_for_order` (Celery task, roda síncrona no
   mesmo processo — sem worker dedicado, ver seção de deploy do `README.md`).
3. A **plataforma compra a etiqueta** na SuperFrete com o frete que o
   comprador pagou. A vendedora **não paga nada**.
4. Vendedora recebe e-mail (`emails/label_ready.txt`) com o link do PDF e
   posta no ponto compatível com a transportadora indicada na etiqueta.
5. Rastreio sincroniza sozinho (`poll_active_shipments`, Render Cron Job de
   hora em hora — `manage.py poll_shipments`) e o comprador acompanha cada
   etapa em `/compras/`.

A SuperFrete exige endereço completo de retorno. Novas lojas informam rua,
número, bairro, cidade e UF no onboarding; esses campos são privados. Lojas
criadas antes da migration `stores.0007` precisam completar o endereço no
admin antes da primeira etiqueta. A etiqueta usa o nome/documento neutro da
plataforma e o endereço operacional de postagem da vendedora.

---

## 4. Retenção e liberação do saldo (escrow do nosso lado)

Implementado em `apps/wallet/services.py` + `apps/shipping/`:

1. Pagamento confirma → `credit_sale()` cria o crédito **retido**
   (`available_at` = hoje + teto de segurança de 30 dias).
2. Rastreio marca **entregue** → `mark_delivered()` muda o status, **sem
   liberar**.
3. Comprador tem **24h** (`DELIVERY_CONFIRMATION_WINDOW_HOURS`) para:
   - **Confirmar** (`POST /api/pedidos/<id>/recebimento/` com `confirm`) →
     `release_sale()` libera na hora; ou
   - **Contestar** (`dispute`) → trava para análise, pedido vira `disputed`.
4. Sem resposta, `release_confirmed_deliveries` (Render Cron Job a cada
   30 min — `manage.py release_deliveries`) libera automaticamente após a
   janela.
5. Teto de 30 dias garante que extravio/rastreio travado não prenda o
   dinheiro pra sempre (compatível com o máximo de 45 dias do escrow Asaas).

Saque sempre para a **chave Pix = CPF da vendedora** (`request_withdrawal`).

---

## 5. Maioridade e responsabilidade jurídica (modelo Privacy + doc-sign)

### Como a Privacy.com.br faz (pesquisa jul/2026)
- **Criadoras/vendedoras**: KYC com análise de **documento + dados de
  identificação + prova de autenticidade** da pessoa responsável pelo perfil.
- **Assinantes/compradores**: processo de identificação que **confirma 18+**.
- **Saque**: verificação de **titularidade da conta de destino**, com
  mecanismos que **impedem transferência para terceiros** — exatamente o que
  já fazemos (saque só pra chave CPF da titular).
- **Moderação**: tecnologia (IA) + revisão humana.

O que já temos alinhado a esse modelo: verificação de idade por CPF+biometria
(`AgeVerification.validated_birth_date`, idade oficial da base do CPF),
telefone vinculado ao CPF, KYC de vendedora com documento+selfie, saque só
pro CPF, e moderação prévia.

Fontes: [Privacy — verificação de identidade](https://privacy.com.br/verificacaoidentidade) ·
[Privacy — do cadastro ao saque](https://blog.privacy.com.br/do-cadastro-ao-saque-como-a-privacy-garante-a-seguranca-de-criadores-e-usuarios-dentro-da-rede/) ·
[Lei 15.211/2025 — guia 2026](https://mancheteesportiva.com.br/enciclopedia/lei-verificacao-idade-brasil-guia-2026/510/)

### Assinatura eletrônica do termo (Clicksign / D4Sign / ZapSign)
O checkbox de aceite do termo de maioridade + cessão de imagem serve para o
MVP, mas para **força probatória plena** o termo deve ser **assinado
eletronicamente** com trilha de auditoria (IP, timestamp, hash do documento).
Pesquisa (jul/2026): **Clicksign** e **D4Sign** são as líderes no Brasil,
com validade jurídica (MP 2.200-2/ICP-Brasil), servidores no país e ~16
métodos de autenticação do signatário. **ZapSign** é a opção mais barata.

Campos já preparados no modelo (`SellerKYC.esign_provider`,
`esign_document_ref`, `esign_signed_at`, `esign_signed_document_url`) — falta
só plugar o SDK/webhook do provider escolhido.

Fontes: [Clicksign](https://www.clicksign.com/) ·
[D4Sign](https://d4sign.com.br/) ·
[Clicksign — validade jurídica](https://www.clicksign.com/validade-juridica)

---

## 6. Passo a passo de implementação

### Pré-requisitos (contas e contratos)
- [ ] Conta **Asaas** aprovada **por escrito** para o nicho (vestuário íntimo
      usado entre PF). Ativar Split + Subcontas + **Conta Escrow**.
- [ ] Conta **SuperFrete** (sandbox para dev, produção depois), token de API
      e saldo suficiente para finalizar etiquetas.
- [ ] Provider de **KYC/idade** (idwall, unico, CAF) — CPF+biometria.
- [ ] Bureau **telefone×CPF** (Serpro Datavalid, idwall) + provider de **SMS**
      (Zenvia, Twilio, AWS SNS).
- [ ] Provider de **NFS-e** (Focus NFe) + CNPJ com **razão social neutra**
      (cobrança discreta).
- [ ] Provider de **assinatura eletrônica** (Clicksign/D4Sign/ZapSign).

### Variáveis de ambiente (ver `backend/.env.example`)
```
PAYMENT_PROVIDER=asaas
ASAAS_API_KEY=...            ASAAS_WEBHOOK_TOKEN=...
SHIPPING_PROVIDER=superfrete
SUPERFRETE_TOKEN=...         SUPERFRETE_SANDBOX=True
SUPERFRETE_SERVICES=1,2,17,3
PLATFORM_COMMISSION_PERCENT=20
PACKAGING_FEE=3.90
DELIVERY_CONFIRMATION_WINDOW_HOURS=24
PHONE_CPF_BUREAU_URL=...     PHONE_CPF_BUREAU_API_KEY=...
SMS_PROVIDER_URL=...         SMS_PROVIDER_API_KEY=...
NFSE_PROVIDER_API_KEY=...    PLATFORM_CNPJ=...  PLATFORM_MUNICIPAL_SERVICE_CODE=...
```

### Migrar e subir
```bash
cd backend
pip install -r requirements.txt
npm install && npm run build:css
python manage.py migrate
python manage.py createsuperuser
# dev rapido sem Postgres (producao usa Postgres real - ver README.md):
#   USE_LOCMEM_CACHE=True DATABASE_URL=sqlite:///db.sqlite3
python manage.py runserver
```

### Configurar webhooks
- **Asaas** → `POST https://SEU_DOMINIO/webhooks/asaas/` (header
  `Asaas-Access-Token` = `ASAAS_WEBHOOK_TOKEN`). Eventos: `PAYMENT_CONFIRMED`,
  `PAYMENT_REFUNDED`, `PAYMENT_CHARGEBACK_REQUESTED`.
- **KYC** → `POST https://SEU_DOMINIO/webhooks/kyc/` (header
  `X-Kyc-Webhook-Token` = `AGE_KYC_API_KEY`).
- **SuperFrete**: o rastreio é puxado por polling (`poll_active_shipments`);
  webhook não é necessário para o MVP.

### O que já está pronto no código
- Modelo de comissão (`Product.payout_amount` → `price`), sem paywall.
- Checkout sem assinatura, com trava de CPF do pagador.
- Cotação de frete do CEP da vendedora + embalagem embutida.
- Compra automática de etiqueta + e-mail com PDF e ponto de coleta.
- Confirmação de recebimento + liberação automática em 24h.
- NF de serviço + e-mails (confirmação, NF, postagem/rastreio).
- Campos de assinatura eletrônica no KYC.

### O que falta plugar (integração real dos fornecedores)
- SDK do provider de KYC/biometria na página de verificação de idade.
- Chamada real do bureau telefone×CPF e do provider de SMS.
- Webhook/SDK do provider de assinatura eletrônica do termo.
- Credenciais reais do Asaas, SuperFrete e Focus NFe (hoje rodam em modo
  dev/sandbox, que **falha fechado** em produção sem credencial).

---

## 7. Checklist de teste (antes de abrir pro público)
- [ ] Anunciar um item e conferir o cálculo comissão (payout → preço).
- [ ] Comprar sem assinatura, pagando via Pix de conta do **próprio CPF**
      (deve passar) e de **terceiro** (deve estornar).
- [ ] Etiqueta comprada automaticamente e e-mail recebido com PDF + ponto.
- [ ] Rastreio atualizando as etapas em `/compras/`.
- [ ] Confirmar recebimento libera saldo; sem confirmar, libera em 24h.
- [ ] Saque cai só na chave Pix = CPF da vendedora.
- [ ] NF de serviço emitida e e-mail enviado (sem conteúdo explícito).
- [ ] Todos os itens do `docs/BASE_JURIDICA.md` § 7 revisados por advogado.
