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
| 11 | `SEED_PAYMENT_TEST=False` depois do primeiro teste de pagamento | Senão a loja de teste com itens de R$ 5 fica pública |

## 2. Teste de fumaça (fazer com dinheiro real, valor baixo)

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
| Verificação biométrica de idade (`AGE_KYC_API_KEY`) | Não contratada; webhook fica fechado (503) | O age gate é só declaratório. É a maior dívida legal do projeto (Lei 15.211/2025) |
| KYC de vendedora (`REQUIRE_SELLER_KYC=False`) | Desligado no soft-launch | Qualquer conta abre loja |
| Verificação de telefone (bureau + SMS) | Sem provider configurado | Pedido personalizado exige `is_phone_verified`, então fica bloqueado na prática |
| NFS-e (`NFSE_PROVIDER_API_KEY`) | Não configurada; a task pula sem erro | Comissão sem nota fiscal |
| Cotação de frete real | `CHECKOUT_FREE_SHIPPING=True` (frete R$ 0) | A vendedora paga o envio do próprio bolso |
| Cartão de crédito | Só Pix implementado | Perde conversão de quem não usa Pix |
| Boost de loja | `StoreBoostPurchaseView` cria o boost sem cobrar | Receita não realizada — desative a compra ou implemente a cobrança |
| Mídia em disco do Render | `/var/data` com 5 GB | Disco cheio derruba upload; migrar para S3 antes de escalar |
| Painel da vendedora para tipo/adicionais/arquivos | Só pelo admin do Django | A vendedora não consegue criar anúncio digital nem adicional sozinha |
| Chat comprador↔vendedora | Só perguntas públicas no anúncio | Combinado de item sob encomenda fica sem canal privado |
| Reembolso do valor em custódia | A contestação trava o repasse, mas o estorno é manual no painel do Asaas | Devolução depende de ação humana |

## 5. Monitoramento mínimo

- Render → Logs: procurar por `Falha no repasse`, `Falha no Pix automatico`,
  `Asaas` com nível ERROR.
- Admin → Pedidos com `status=awaiting_payment` e `expires_at` no passado:
  se acumular, o cron `expire-orders` parou.
- Admin → `WithdrawalRequest` com `status=failed`: repasse que não saiu,
  precisa de Pix manual pelo painel do Asaas.
