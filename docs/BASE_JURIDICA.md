# Base Jurídica do Projeto — Renda & Renda

> **Status:** documento de premissas do projeto. Consolidado a partir de 4 análises independentes + pesquisa sobre a Lei 15.211/2025.
> **Não é parecer jurídico.** Deve ser validado por advogado especializado em direito digital (criminal + consumidor + LGPD) antes do lançamento.
> **Regra do projeto:** nenhuma feature entra em produção se violar qualquer item deste documento.

---

## 1. O que o site É (e o que NÃO é)

| O site É | O site NÃO é |
|---|---|
| Classificados +18 de itens íntimos usados, entre adultos | Vendedor dos itens |
| Intermediador de anúncio e de contato | Intermediador de pagamento do item |
| Cobrador de assinatura (vendedora), desbloqueio de contato (comprador) e boosts | Marketplace que organiza entrega, preço ou garantia do produto |

A compra e venda do item ocorre **diretamente entre vendedora e comprador, fora da plataforma**. O site nunca processa o pagamento do item, nunca sugere preço, nunca gerencia entrega.

## 2. Fundamentos de licitude (consenso das 4 análises)

1. **Não há proibição legal direta.** Vender peça íntima usada entre adultos não é crime nem contravenção no Brasil. O objeto do contrato é lícito (art. 104 do Código Civil) — venda de bem móvel; a finalidade erótica não torna o negócio ilícito.
2. **Não configura rufianismo nem favorecimento à prostituição.** Os arts. 228–230 do Código Penal tratam de intermediação de *serviços sexuais*. Venda de produto físico não é serviço sexual; a intermediação via site não se enquadra nesses tipos penais. Zona pouco testada nos tribunais — manter distância máxima da fronteira (ver seção 3).
3. **Intermediação C2C com taxa/comissão é, em regra, possível** entre maiores de 18 anos.

## 3. Linhas vermelhas — proibições absolutas

Qualquer um destes itens muda o enquadramento jurídico e é **banido da plataforma, sem exceção**:

1. **Menores de 18 anos em qualquer papel** — cadastro, compra, venda, imagens, menção. Envolver menor, mesmo sem saber, gera responsabilização gravíssima (ECA e Código Penal). Por isso a verificação de idade é real, não checkbox, e os registros são guardados.
2. **Qualquer indício de serviço sexual**: encontros, programas, "acompanhante", conteúdo sexual sob encomenda, webcam/atendimento. Anúncios só de **itens físicos + mídia do item**.
3. **Pornografia ilegal / exploração sexual** de qualquer natureza.
4. **Promessas sanitárias enganosas** ("higienizado", "seguro", "sem risco") sem base — risco de publicidade enganosa (CDC).

**Consequência operacional:** moderação prévia de todo anúncio; filtros automáticos + revisão humana em anúncios e chat; banimento por CPF (não só por e-mail) com registro da ocorrência.

## 4. Obrigações legais da plataforma

### 4.1 Verificação de idade — Lei 15.211/2025 (ECA Digital / "Lei Felca")
- Em vigor plenamente desde **17/03/2026**. Autodeclaração de idade ("tenho +18") é **proibida**.
- Exige mecanismos **confiáveis e auditáveis** de verificação de idade. Padrão do projeto: CPF + data de nascimento validados em base oficial + prova de vida facial; para vendedoras, KYC completo (documento frente/verso + selfie com documento + termo de maioridade e cessão de imagem).
- Dados coletados para verificação só podem ser usados **para essa finalidade** — proibido reutilizar (ex.: publicidade).
- Fiscalização: **ANPD**. Sanções: advertência, multa de até 10% do faturamento no Brasil (teto de R$ 50 milhões por infração) ou suspensão das atividades.
- Remoção imediata de conteúdo que indique exploração/abuso assim que comunicado, **independentemente de ordem judicial**, com reporte às autoridades.

### 4.2 LGPD
- Os dados de cadastro **revelam, por inferência, vida sexual** → tratados como **dado sensível** (art. 5º, II).
- Obrigações: minimização de coleta; criptografia em repouso; política de privacidade específica; exclusão de conta e dados a pedido; encarregado (DPO); storage segregado e com retenção mínima para dados de verificação/KYC.
- Vazamento = multa + dano moral em escala. Segurança é requisito, não feature.

### 4.3 CDC e Marco Civil da Internet
- Como intermediador, o site responde por falhas nos termos do Marco Civil (Lei 12.965/2014) e, quando houver relação de consumo, do CDC.
- Jurisprudência (STJ): plataforma que atua como **mera divulgadora de anúncios** (classificados) tem responsabilização reduzida; plataforma que intermedia o pagamento do produto pode responder solidariamente. → Reforça a decisão de **nunca processar o pagamento do item**.
- Termos de Uso bem escritos definindo o papel de classificados **reduzem, mas não eliminam**, a exposição. Canal de denúncia visível e resposta rápida são parte da diligência.

### 4.4 Fiscal / societário
- CNPJ (CNAEs de portais/intermediação), conta PJ com **razão social neutra** (cobrança discreta no extrato).
- Emissão de nota fiscal sobre assinaturas, desbloqueios e boosts.
- Declaração de renda das vendedoras é responsabilidade delas; incluir aviso nos Termos.
- **Programa de embaixadoras** (`apps.ambassadors`, ver `docs/checkout.md` § 8): o bônus pago à
  vendedora que indica é registrado como bônus de venda indicada, não como repasse de comissão da
  plataforma — decisão de produto que ainda precisa de validação de contador/advogado, como todo o
  resto desta seção, antes de valer para o programa em escala.

## 5. Pagamentos

- **Gateways mainstream (Mercado Pago, PagSeguro, Stripe, bancos) proíbem o nicho nos termos** → risco de congelamento de saldo e banimento. **Nunca integrar escondendo o nicho.**
- Estratégia: **Pix-first** (sem chargeback; Pix Automático para assinaturas) com gateway que aceite o nicho **com aprovação por escrito**. Cartão como secundário via processadores adult-friendly internacionais (CCBill, Segpay, Epoch, Verotel), avaliando custo.
- Descritor de fatura e e-mails transacionais **sem conteúdo explícito**.

## 6. Aquisição e marca

- Google Ads, Meta e app stores não aceitam o nicho → aquisição por **SEO orgânico, X/Twitter e tráfego direto**. Age gate em todo o site e classificação adequada (meta RTA + rating adult).
- Estrutura: páginas públicas indexáveis sem nudez explícita; área logada com `noindex`.

## 7. Checklist pré-lançamento

- [ ] Parecer de advogado (criminal + consumidor + LGPD) validando este documento
- [ ] Termos de Uso + Política de Privacidade redigidos por advogado
- [ ] Termo digital de maioridade e cessão de imagem da vendedora
- [ ] CNPJ aberto, conta PJ, razão social neutra
- [ ] Contrato com provedor de verificação de idade/KYC (idwall, unico, CAF ou similar)
- [ ] Gateway Pix com aceite formal (por escrito) do nicho
- [ ] Fila de moderação prévia implementada e testada
- [ ] Filtros anti-serviço-sexual e anti-contato (regex + OCR) ativos
- [ ] Botão de denúncia em toda página de conteúdo
- [ ] Fluxo de remoção imediata + reporte às autoridades documentado
- [ ] Criptografia em repouso dos dados sensíveis e de KYC verificada
- [ ] Canal de exclusão de conta/dados funcionando (LGPD)
