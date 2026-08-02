"""
Preenche o texto próprio de cada categoria (`Category.description`).

    python manage.py seed_category_texts            # só o que está vazio
    python manage.py seed_category_texts --dry-run  # mostra sem gravar
    python manage.py seed_category_texts --overwrite

Sem esse texto, `/categorias/<slug>/` cai num parágrafo genérico que só
muda o nome da categoria — sete páginas quase idênticas, que é o caso
clássico de conteúdo duplicado que o Google descarta.

Regras que TODO texto aqui respeita (docs/BASE_JURIDICA.md § 3):
  - nenhuma promessa sanitária ("higienizado", "seguro", "sem risco") —
    seria publicidade enganosa (CDC art. 37);
  - nenhum indício de serviço: encontro, programa, acompanhante, webcam,
    atendimento ou encomenda de conteúdo;
  - nenhum prazo/percentual numérico que vive em `settings` (prazo de
    disputa, comissão) — texto e configuração não podem divergir.

Este é um rascunho para revisão humana, não texto jurídico aprovado.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.catalog.models import Category

DESCRIPTIONS = {
    "calcinhas": (
        "Calcinhas usadas anunciadas por vendedoras com identidade conferida. "
        "Cada anúncio traz modelo, tamanho, tecido e o tempo de uso declarado "
        "por quem vende — leia a descrição e use a pergunta pública do anúncio "
        "antes de comprar. A peça viaja pelos Correios em caixa sem logo e sem "
        "remetente que entregue o assunto, e o valor pago fica retido na "
        "plataforma até você confirmar que recebeu."
    ),
    "meias": (
        "Meias 7/8, soquete, meia-calça e arrastão usadas, com o tempo de uso "
        "declarado no anúncio. É a categoria mais leve da vitrine: peça pequena "
        "costuma fechar com o frete mais barato do site. O envio sai em "
        "embalagem neutra e com rastreio, e o pagamento só é liberado para a "
        "vendedora depois que você confirma o recebimento — ou dentro do prazo "
        "descrito em Como funciona, se você não responder."
    ),
    "sutias": (
        "Sutiãs usados anunciados por quem realmente usou: numeração, modelo "
        "(bojo, triângulo, renda) e tempo de uso vêm descritos no próprio "
        "anúncio. Muitas vendedoras publicam a calcinha do mesmo conjunto em "
        "separado — vale abrir a loja e ver o que combina antes de fechar a "
        "sacola. Chega pelos Correios em caixa sem identificação, e o dinheiro "
        "fica em custódia até a confirmação de recebimento."
    ),
    "bodys": (
        "Bodys, corselets e peças de renda inteiriças usadas, com tamanho, "
        "tecido e tempo de uso descritos pela vendedora. Por serem peças "
        "maiores, vale conferir a medida antes de comprar: a pergunta feita no "
        "anúncio fica pública e a resposta serve para quem chegar depois. "
        "Envio pelos Correios em embalagem neutra, com o pagamento retido na "
        "plataforma até você confirmar que recebeu."
    ),
    "sungas": (
        "Sungas e cuecas usadas, a linha masculina da vitrine. Modelo, tamanho "
        "e tempo de uso ficam descritos no anúncio, e dá para perguntar na "
        "própria página antes de comprar. Vale a mesma regra do resto do site: "
        "quem anuncia teve documento e selfie conferidos, o envio sai em caixa "
        "sem logo e sem remetente que entregue o conteúdo, e o valor fica em "
        "custódia até a confirmação de recebimento."
    ),
    "packs": (
        "Packs de fotos e vídeos autorais, produzidos e publicados pela própria "
        "vendedora. Não tem frete nem espera: o arquivo fica disponível na "
        "página do pedido assim que o pagamento é confirmado. Todo pack passa "
        "por moderação antes de ficar público e é sempre material pronto — a "
        "plataforma não intermedia encomenda de conteúdo, encontro, chamada de "
        "vídeo nem qualquer forma de atendimento."
    ),
    "conteudo-digital": (
        "Conteúdo digital além dos packs: ensaios avulsos, coleções temáticas e "
        "arquivos publicados para download imediato. Sem endereço, sem frete e "
        "sem rastreio — o pagamento confirma e o arquivo aparece na página do "
        "pedido. Cada item passa por moderação prévia antes de entrar na "
        "vitrine, e vale a mesma linha do restante do site: só material pronto, "
        "nunca encomenda de conteúdo ou atendimento."
    ),
}


class Command(BaseCommand):
    help = "Preenche Category.description com o texto de SEO de cada categoria."

    def add_arguments(self, parser):
        parser.add_argument("--overwrite", action="store_true", help="Substitui texto já escrito.")
        parser.add_argument("--dry-run", action="store_true", help="Mostra o que faria, sem gravar.")

    def handle(self, *args, **options):
        overwrite = options["overwrite"]
        dry_run = options["dry_run"]
        limit = Category._meta.get_field("description").max_length

        written = skipped = missing = 0
        for slug, text in DESCRIPTIONS.items():
            if len(text) > limit:
                self.stderr.write(f"  {slug}: {len(text)} caracteres — passa do limite de {limit}.")
                continue

            category = Category.objects.filter(slug=slug).first()
            if category is None:
                missing += 1
                self.stdout.write(f"  {slug}: categoria não existe neste banco, pulando.")
                continue
            if category.description and not overwrite:
                skipped += 1
                self.stdout.write(f"  {slug}: já tem texto, pulando (use --overwrite).")
                continue

            if not dry_run:
                category.description = text
                category.save(update_fields=["description"])
            written += 1
            self.stdout.write(f"  {slug}: {len(text)} caracteres {'(dry-run)' if dry_run else 'gravados'}.")

        self.stdout.write(
            self.style.SUCCESS(
                f"{written} categoria(s) preenchida(s), {skipped} mantida(s), {missing} inexistente(s)."
            )
        )
