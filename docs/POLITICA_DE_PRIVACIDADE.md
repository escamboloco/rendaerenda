# Política de Privacidade — Renda & Renda

> **RASCUNHO DE TRABALHO.** Não é documento juridicamente válido até ser revisado e aprovado por advogado especializado em LGPD (item do checklist em `docs/BASE_JURIDICA.md`). Não publicar em produção sem essa revisão. O Encarregado (DPO) exigido pela LGPD ainda precisa ser nomeado e seus dados de contato incluídos aqui.

## 1. Dados sensíveis — tratamento especial

Pelo próprio objeto da Plataforma, os dados de cadastro revelam, por inferência, informação sobre vida sexual do titular, o que os torna **dado sensível** nos termos do art. 5º, II, da Lei Geral de Proteção de Dados (Lei 13.709/2018). Todo o tratamento descrito abaixo segue o padrão reforçado exigido para essa categoria de dado.

## 2. Dados que coletamos

| Categoria | Dados | Finalidade | Base legal |
|---|---|---|---|
| Cadastro | Nome, e-mail, CPF, data de nascimento | Autenticação, verificação de idade | Cumprimento de obrigação legal (Lei 15.211/2025) |
| Verificação de idade | Selfie/vídeo de prova de vida, resultado da checagem biométrica | Comprovar maioridade de forma auditável | Cumprimento de obrigação legal |
| KYC de vendedora | Documento de identidade, selfie com documento, termo de cessão de imagem | Vincular a identidade real à loja, prevenir fraude e uso por menores | Cumprimento de obrigação legal / execução de contrato |
| Transação | Valor, método de pagamento, status — **nunca número de cartão completo** | Processar cobrança e split via PSP | Execução de contrato |
| Envio | Endereço, CEP, código de rastreio | Calcular frete e permitir rastreio | Execução de contrato |
| Navegação | Cookies de sessão, confirmação de age gate | Segurança e funcionamento do site | Legítimo interesse |

## 3. O que NÃO fazemos

- Não reutilizamos os dados de verificação de idade/KYC para nenhuma outra finalidade, inclusive publicidade — uso exclusivo para a checagem exigida por lei.
- Não vendemos dados a terceiros.
- Não armazenamos número completo de cartão de crédito — a tokenização é feita pelo PSP.
- Não exibimos publicamente CPF, endereço completo ou documentos.

## 4. Compartilhamento com terceiros

Compartilhamos o mínimo necessário com: (a) o provedor de verificação de idade/KYC (ex.: idwall, unico, CAF); (b) a Instituição de Pagamento (PSP) para processar a cobrança e o split; (c) os Correios, para cálculo de frete e rastreio; (d) autoridades competentes, quando exigido por lei ou em caso de suspeita de exploração de menor — nesse último caso, independentemente de ordem judicial, conforme a Lei 15.211/2025.

## 5. Segurança

- Dados sensíveis e de KYC são armazenados criptografados em repouso, em storage segregado com retenção mínima.
- Mídia (fotos/vídeos de produtos) é servida por URLs assinadas de curta duração, nunca por link público direto.
- Logs de sistema nunca registram senha, número de cartão, documento ou CPF completo.
- Acesso interno aos dados de KYC é restrito e registrado (auditável).

## 6. Direitos do titular

Você pode, a qualquer momento, solicitar: confirmação de tratamento, acesso aos dados, correção, anonimização ou eliminação de dados desnecessários, portabilidade, e revogação de consentimento. Para dados cuja retenção é exigida por lei (ex.: registros de verificação de idade, dados fiscais), a eliminação ocorre ao fim do prazo legal de retenção.

Solicitações podem ser feitas em [canal a definir — e-mail do DPO]. Prazo de resposta: até 15 dias.

## 7. Retenção

Dados de verificação de idade e KYC são mantidos pelo prazo mínimo exigido para fins de auditoria e defesa legal, e depois eliminados ou anonimizados. Dados de transação são mantidos pelo prazo fiscal aplicável (nota fiscal).

## 8. Encarregado (DPO)

[Nome e contato do Encarregado a definir antes do lançamento — exigido pela LGPD, item pendente no checklist de `docs/BASE_JURIDICA.md`.]

## 9. Autoridade de fiscalização

A Autoridade Nacional de Proteção de Dados (ANPD) é a autoridade competente para receber reclamações relativas a esta Política.
