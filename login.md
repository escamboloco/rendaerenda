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

## Vendedoras (22 lojas ativas, KYC aprovado)

| Loja | E-mail (login) | URL da loja |
|---|---|---|
| Ateliê da Luna | luna@demo.local | `/loja/atelie-da-luna/` |
| Valentina Secreta | valentina@demo.local | `/loja/valentina-secreta/` |
| Morena Misteriosa | morena@demo.local | `/loja/morena-misteriosa/` |
| Ruiva do Sul | ruiva@demo.local | `/loja/ruiva-do-sul/` |
| Gata Paulista | gata@demo.local | `/loja/gata-paulista/` |
| Bella Íntima | bella@demo.local | `/loja/bella-intima/` |
| Nina da Noite | nina@demo.local | `/loja/nina-da-noite/` |
| Clara Sedução | clara@demo.local | `/loja/clara-seducao/` |
| Maya Velvet | maya@demo.local | `/loja/maya-velvet/` |
| Sofia Lace | sofia@demo.local | `/loja/sofia-lace/` |
| Iara do Centro | iara@demo.local | `/loja/iara-do-centro/` |
| Priscila Pink | priscila@demo.local | `/loja/priscila-pink/` |
| Helena Silk | helena@demo.local | `/loja/helena-silk/` |
| Bruna Fitness | bruna@demo.local | `/loja/bruna-fitness/` |
| Camila Closet | camila@demo.local | `/loja/camila-closet/` |
| Duda Secret | duda@demo.local | `/loja/duda-secret/` |
| Fernanda Rouge | fernanda@demo.local | `/loja/fernanda-rouge/` |
| Giovana Soft | giovana@demo.local | `/loja/giovana-soft/` |
| Isabela Night | isabela@demo.local | `/loja/isabela-night/` |
| Juliana Bloom | juliana@demo.local | `/loja/juliana-bloom/` |
| Karina Heat | karina@demo.local | `/loja/karina-heat/` |
| Lara Privê | lara@demo.local | `/loja/lara-prive/` |

Cada vendedora tem: ~3 produtos publicados (fotos públicas Unsplash ou fallback),
painel em `/vendedora/`, vendas/avaliações nas primeiras lojas e follows de compradores.

## Compradores

| Apelido público | E-mail (login) | Observação |
|---|---|---|
| Gato Misterioso | comprador1@demo.local | Compras + pedido personalizado |
| Admirador Secreto | comprador2@demo.local | Contra-proposta pendente |
| (sem apelido) | comprador3@demo.local | Identificador neutro |
| Colecionador Quiet | comprador4@demo.local | Segue várias lojas |
| Fã Discreto | comprador5@demo.local | Segue várias lojas |

## Como popular

```bash
cd backend
python manage.py migrate
python manage.py seed_demo
```
