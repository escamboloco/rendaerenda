# Contas de demonstração — Renda & Renda

> ⚠️ **APENAS DESENVOLVIMENTO/DEMONSTRAÇÃO.** Estas contas são criadas
> pelo comando `python manage.py seed_demo`, que **se recusa a rodar com
> `DJANGO_DEBUG=False`** — elas nunca devem existir em produção. As senhas
> abaixo são públicas de propósito (estão no código do seed); jamais
> reutilize em ambiente real.

**Senha de todas as contas:** `demo12345`

O login no site é feito pelo **e-mail**. O admin (`/admin/`) usa o username.

## Administração

| Papel | Username | E-mail | Onde usar |
|---|---|---|---|
| Superusuário | `admin` | admin@demo.local | `/admin/` (moderação, pedidos, tudo) |

## Vendedoras (lojas ativas, KYC aprovado)

| Loja | E-mail (login) | URL da loja |
|---|---|---|
| Ateliê da Luna | luna@demo.local | `/loja/atelie-da-luna/` |
| Valentina Secreta | valentina@demo.local | `/loja/valentina-secreta/` |
| Morena Misteriosa | morena@demo.local | `/loja/morena-misteriosa/` |
| Ruiva do Sul | ruiva@demo.local | `/loja/ruiva-do-sul/` |
| Gata Paulista | gata@demo.local | `/loja/gata-paulista/` |

Cada vendedora tem: 4 produtos publicados (com fotos ilustrativas geradas),
vendas entregues com saldo já liberado na carteira (`/carteira/`) e
avaliações reais alimentando o ranking (`/ranking/`).

## Compradores (idade e telefone verificados)

| Apelido público | E-mail (login) | Observação |
|---|---|---|
| Gato Misterioso | comprador1@demo.local | Tem compras entregues + 1 pedido personalizado pendente |
| Admirador Secreto | comprador2@demo.local | Tem 1 pedido personalizado com contra-proposta pra decidir |
| (sem apelido) | comprador3@demo.local | Testa o identificador neutro na interação |

## Como recriar tudo do zero

```bash
cd backend
rm -f db.sqlite3 && rm -rf media
DJANGO_DEBUG=True DATABASE_URL=sqlite:///db.sqlite3 USE_LOCMEM_CACHE=True \
  python manage.py migrate && python manage.py seed_demo
```
