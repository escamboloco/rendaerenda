"""
Gera o PDF de análise de riscos do Renda & Renda.

Rodar:  python scripts/gerar_relatorio_riscos.py
Saída:  docs/RISCOS_RENDA_E_RENDA.pdf
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parent.parent / "docs" / "RISCOS_RENDA_E_RENDA.pdf"

INK = colors.HexColor("#1a1118")
WINE = colors.HexColor("#8e0f31")
GREY = colors.HexColor("#5b5b66")
LIGHT = colors.HexColor("#f3f0f2")
RED = colors.HexColor("#a11024")
AMBER = colors.HexColor("#8a5a12")

styles = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=styles["Title"], fontName="Times-Bold",
                            fontSize=26, leading=30, textColor=INK, spaceAfter=4),
    "sub": ParagraphStyle("s", parent=styles["Normal"], fontName="Helvetica",
                          fontSize=10.5, leading=15, textColor=GREY, spaceAfter=18),
    "h1": ParagraphStyle("h1", parent=styles["Heading1"], fontName="Times-Bold",
                         fontSize=17, leading=21, textColor=WINE, spaceBefore=18, spaceAfter=8),
    "h2": ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                         fontSize=11.5, leading=15, textColor=INK, spaceBefore=12, spaceAfter=5),
    "body": ParagraphStyle("b", parent=styles["Normal"], fontName="Helvetica",
                           fontSize=9.8, leading=14.5, textColor=INK,
                           alignment=TA_JUSTIFY, spaceAfter=7),
    "small": ParagraphStyle("sm", parent=styles["Normal"], fontName="Helvetica",
                            fontSize=8.6, leading=12.5, textColor=GREY, spaceAfter=6),
    "cellh": ParagraphStyle("ch", parent=styles["Normal"], fontName="Helvetica-Bold",
                            fontSize=8.8, leading=12, textColor=colors.white),
    "cell": ParagraphStyle("c", parent=styles["Normal"], fontName="Helvetica",
                           fontSize=8.6, leading=12, textColor=INK),
}


def p(text, style="body"):
    return Paragraph(text, S[style])


def rule():
    return HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#ddd6da"),
                      spaceBefore=6, spaceAfter=10)


def risk_block(number, title, severity, body_paragraphs):
    tone = {"CRÍTICO": RED, "ALTO": AMBER, "MÉDIO": GREY}[severity]
    header = Table(
        [[Paragraph(f"{number}. {title}", S["cellh"]), Paragraph(severity, S["cellh"])]],
        colWidths=[13.2 * cm, 3.0 * cm],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), tone),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    return [header, Spacer(1, 6)] + [p(t) for t in body_paragraphs] + [Spacer(1, 6)]


def table(headers, rows, widths):
    data = [[Paragraph(h, S["cellh"]) for h in headers]]
    data += [[Paragraph(c, S["cell"]) for c in row] for row in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#ddd6da")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.2 * cm, "Renda & Renda — análise técnica de riscos")
    canvas.drawRightString(19 * cm, 1.2 * cm, f"pág. {doc.page}")
    canvas.restoreState()


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=2 * cm,
        title="Renda & Renda — análise de riscos", author="Análise técnica",
    )
    f = []

    # ------------------------------------------------------------- capa
    f.append(p("Renda &amp; Renda", "title"))
    f.append(p(
        "Análise honesta de riscos — operação de marketplace +18 com recebimento "
        "em conta pessoa física", "sub"))
    f.append(rule())

    f.append(p(
        "<b>Antes de tudo:</b> não sou advogado nem contador, e este documento não é "
        "parecer jurídico nem consultoria tributária. É uma análise técnica de quem "
        "construiu o sistema e enxerga onde ele encosta em regras sérias. Os pontos "
        "1 e 2 precisam ser validados com um contador e um advogado <b>antes</b> do "
        "primeiro real entrar. Estou sendo direto porque você pediu sinceridade: "
        "há riscos aqui que podem custar muito mais do que o site vai faturar no "
        "começo."))
    f.append(Spacer(1, 4))

    f.append(p("Resumo em uma frase", "h2"))
    f.append(p(
        "O software está sólido e pronto para vender; <b>a estrutura jurídico-financeira "
        "não está</b>. Receber dinheiro de terceiros em conta PF, segurando valores em "
        "custódia, é a parte mais arriscada de tudo o que existe neste projeto — e é a "
        "única que nenhuma linha de código resolve."))

    f.append(p("Os riscos, do mais grave para o menos", "h1"))
    f.append(p(
        "Classifiquei por <b>quanto custa se der errado</b>, não por probabilidade. "
        "Um risco crítico pouco provável ainda merece o topo da lista quando o "
        "desfecho é perder a conta bancária ou responder processo."))

    # ------------------------------------------------------- risco 1
    f += risk_block(1, "Receber dinheiro de terceiros em conta PF", "CRÍTICO", [
        "Hoje o dinheiro do comprador entra na sua conta Asaas pessoa física, fica "
        "retido em custódia e depois é repassado à vendedora. Do ponto de vista de "
        "quem olha de fora (Receita, banco, PSP), <b>quem vendeu foi você</b> — o "
        "valor inteiro passou pela sua conta.",

        "<b>O problema tributário é o mais caro.</b> Sem CNPJ, todo valor que entra "
        "tende a ser tratado como rendimento seu, tributado pela tabela do IRPF "
        "(até 27,5%) sobre <b>o total movimentado</b>, não sobre a sua comissão. "
        "Num cenário de R$ 100 mil transacionados no ano, com 20% de comissão, "
        "você ganhou R$ 20 mil — mas pode ser cobrado imposto sobre os R$ 100 mil. "
        "O imposto sozinho passa do que você ganhou.",

        "<b>Movimentação incompatível com a renda declarada.</b> Instituições "
        "financeiras reportam movimentação à Receita (e-Financeira). Uma PF "
        "recebendo dezenas ou centenas de Pix de desconhecidos, todo mês, é "
        "exatamente o padrão que cai em malha e pode virar procedimento fiscal.",

        "<b>Custódia agrava tudo.</b> Guardar dinheiro de terceiro até a entrega — "
        "que é a promessa central do site — é atividade que se aproxima de "
        "serviço de pagamento. Numa conta PF, sem contrato e sem estrutura, você "
        "acumula saldo de terceiros sem base formal para isso.",

        "<b>Sem CNPJ você também não emite nota fiscal da comissão.</b> O sistema "
        "tem o módulo de NFS-e pronto e ele fica inútil: prestar serviço "
        "remunerado sem emitir nota é irregularidade autônoma, além de tirar sua "
        "capacidade de deduzir qualquer despesa.",

        "<b>O que fazer:</b> abrir CNPJ antes de escalar. Simples Nacional com CNAE "
        "de intermediação de negócios costuma ser o caminho, e a tributação incide "
        "sobre a <b>receita de comissão</b>, não sobre o valor bruto que passa. "
        "Converse com um contador que já tenha atendido marketplace — a diferença "
        "entre as duas estruturas, no seu caso, é da ordem de dezenas de milhares "
        "de reais por ano.",
    ])

    # ------------------------------------------------------- risco 2
    f += risk_block(2, "O Asaas pode encerrar a conta e reter o saldo", "CRÍTICO", [
        "Praticamente todo PSP brasileiro tem, nos termos de uso, vedação a "
        "conteúdo adulto. Se a sua conta foi aberta sem declarar o nicho por "
        "escrito, o encerramento por quebra de termos é uma possibilidade concreta "
        "— e costuma vir acompanhado de <b>retenção do saldo por 90 dias ou mais</b>.",

        "O detalhe cruel: no modelo de custódia, o saldo retido <b>não é seu</b>. É "
        "dinheiro de compradores que ainda não viraram entrega e de vendedoras que "
        "ainda não sacaram. Se a conta congelar, você fica devendo a duas pontas ao "
        "mesmo tempo, sem ter como pagar.",

        "<b>O que fazer:</b> obter do Asaas aprovação <b>por escrito</b> do seu ramo "
        "real, com a descrição correta (venda de vestuário íntimo usado entre "
        "pessoas físicas e conteúdo digital adulto). Guarde o e-mail. E tenha um "
        "segundo PSP homologado antes de precisar dele — trocar de gateway com a "
        "operação parada é o pior momento possível.",
    ])

    f.append(PageBreak())

    # ------------------------------------------------------- risco 3
    f += risk_block(3, "Verificação de idade — Lei 15.211/2025 (ECA Digital)", "CRÍTICO", [
        "Hoje o site tem duas camadas: um <i>age gate</i> declaratório na entrada "
        "(a pessoa clica que tem 18) e, para quem vende, verificação com documento "
        "+ selfie com código, conferida por humano. A verificação biométrica com "
        "prova de vida está implementada no código, mas <b>desligada</b>, porque o "
        "bureau ainda não foi contratado.",

        "Clicar num botão não é verificação de idade. A lei trata plataformas com "
        "conteúdo adulto de forma específica, e o descumprimento vai de multa a "
        "determinação de bloqueio. Quem compra hoje não tem a idade checada de "
        "verdade em nenhum momento — só declara o CPF e a data de nascimento no "
        "checkout, dados que o sistema não confronta com base oficial.",

        "<b>O que fazer:</b> contratar um bureau (idwall, Unico, CAF, Serpro "
        "Datavalid) e preencher AGE_KYC_API_URL/AGE_KYC_API_KEY. O código já está "
        "escrito e o passo a passo está em docs/PRODUCAO.md, seção 5. Enquanto não "
        "estiver ligado, a checagem do CPF do pagador é a única barreira real — e "
        "ela prova identidade, não idade.",
    ])

    # ------------------------------------------------------- risco 4
    f += risk_block(4, "Conteúdo íntimo de terceiros e o Marco Civil", "ALTO", [
        "O artigo 21 do Marco Civil trata de imagem íntima divulgada sem "
        "consentimento: basta a notificação da pessoa retratada — <b>não precisa de "
        "ordem judicial</b> — para que a plataforma tenha o dever de remover. Não "
        "removeu rápido, responde junto com quem publicou.",

        "No seu caso o risco é direto: uma vendedora pode publicar foto de outra "
        "pessoa, ou um ex-parceiro pode criar conta e anunciar material de alguém. "
        "O site tem fila de moderação prévia e botão de denúncia, mas <b>a "
        "aprovação é manual e depende de alguém realmente olhar</b>. Se você for a "
        "única pessoa moderando, uma semana de férias vira exposição jurídica.",

        "<b>O que fazer:</b> canal de denúncia visível (existe), prazo interno curto "
        "de remoção, registro de quem aprovou cada anúncio (existe) e o termo de "
        "cessão de imagem assinado por quem vende (existe como checkbox — para "
        "força probatória, migre para assinatura eletrônica).",
    ])

    # ------------------------------------------------------- risco 5
    f += risk_block(5, "Chargeback no cartão depois de a vendedora receber", "ALTO", [
        "O cartão foi habilitado hoje. Pix não tem estorno unilateral, mas cartão "
        "tem: o titular pode contestar a compra <b>meses depois</b>. O seu fluxo "
        "libera o dinheiro para a vendedora em 7 dias.",

        "Resultado: chega o chargeback, o Asaas debita de você, e o dinheiro já foi "
        "embora. O sistema registra saldo negativo na carteira dela e loga o caso "
        "para conciliação humana, mas <b>recuperar o valor na prática é difícil</b> "
        "— e nesse nicho a taxa de contestação costuma ser acima da média, "
        "inclusive por constrangimento de quem comprou.",

        "<b>O que fazer:</b> comece só com Pix e ative o cartão quando tiver "
        "reserva para absorver perdas; ou segure o valor do cartão por prazo maior "
        "que o do Pix. É uma linha de configuração, não uma reescrita.",
    ])

    # ------------------------------------------------------- risco 6
    f += risk_block(6, "LGPD: você guarda dado sensível de verdade", "ALTO", [
        "O banco tem CPF, data de nascimento, endereço completo, documento com "
        "foto e selfie das vendedoras. Some a isso o histórico de compra em um "
        "site adulto — o conjunto permite inferir vida sexual, que a LGPD trata "
        "como <b>dado sensível</b>, com exigência mais alta que dado comum.",

        "Um vazamento aqui não é constrangimento: é dano moral quase presumido, "
        "multiplicado pelo número de pessoas afetadas, mais sanção da ANPD (até 2% "
        "do faturamento, limitado a R$ 50 milhões por infração).",

        "Hoje as fotos de documento ficam em disco no Render, sem criptografia em "
        "repouso configurada. É o ponto mais frágil da parte técnica.",

        "<b>O que fazer:</b> mover mídia para storage privado com URL assinada (o "
        "código já suporta S3, basta configurar), definir prazo de descarte dos "
        "documentos após aprovação, e ter plano de resposta a incidente. Nomear "
        "encarregado de dados (pode ser você) e publicar o contato.",
    ])

    f.append(PageBreak())

    # ------------------------------------------------------- risco 7
    f += risk_block(7, "Você é responsável solidário pelo que vende na sua vitrine", "MÉDIO", [
        "Os Termos dizem que a plataforma só intermedia. Isso ajuda, mas o Código "
        "de Defesa do Consumidor costuma enxergar o marketplace como parte da "
        "cadeia: produto que não chega, chega diferente ou causa problema de saúde "
        "pode ser cobrado de você, não só da vendedora.",

        "Item íntimo usado tem um agravante: não existe regra sanitária clara para "
        "esse comércio, e os Correios têm restrições para determinados conteúdos. "
        "Um problema de saúde relatado por um comprador seria um caso difícil de "
        "defender.",

        "<b>O que fazer:</b> regras explícitas de higienização e embalagem no termo "
        "da vendedora, proibição clara de itens com fluidos corporais (hoje há "
        "categorias no mercado que atravessam essa linha — não copie), e a "
        "custódia funcionando como já está.",
    ])

    # ------------------------------------------------------- risco 8
    f += risk_block(8, "Operação de uma pessoa só", "MÉDIO", [
        "O sistema promete: moderação antes de publicar, KYC conferido em 24h "
        "úteis, disputa analisada por gente de verdade. Tudo isso hoje depende de "
        "<b>você abrir o admin</b>.",

        "Promessa publicada e não cumprida é propaganda enganosa — e, na prática, "
        "é o que mais destrói reputação em marketplace pequeno: anúncio parado "
        "três dias na fila, vendedora reclamando, comprador sem resposta.",

        "<b>O que fazer:</b> ou reserve uma janela diária fixa para a fila, ou "
        "ajuste os prazos publicados para o que você consegue cumprir sozinho. "
        "Prometer 72h e entregar em 24 é melhor que o contrário.",
    ])

    # -------------------------------------------------- o que está pronto
    f.append(p("O que já está resolvido no sistema", "h1"))
    f.append(p(
        "Para você separar o que é risco de estrutura do que é risco de software: "
        "a parte de software está, na minha avaliação, em bom estado. 149 testes "
        "automatizados cobrem o caminho do dinheiro."))
    f.append(Spacer(1, 4))
    f.append(table(
        ["Risco de software", "Como está tratado"],
        [
            ["Pagar a vendedora duas vezes",
             "Webhook idempotente, trava por pedido no banco e marca de repasse enviado. Testado."],
            ["Vender item que não existe mais",
             "Estoque reservado sob lock; pedido não pago expira e devolve a peça à vitrine."],
            ["Cliente pagar e o pedido não confirmar",
             "A tela consulta o Asaas direto, então confirma mesmo se o webhook falhar."],
            ["Preço adulterado no navegador",
             "Todo valor é recalculado no servidor; a sacola guarda só id e quantidade."],
            ["Terceiro marcar pedido como pago",
             "Webhook exige token; sem token configurado o endpoint fica fechado."],
            ["Pagamento por CPF de outra pessoa",
             "Conferido no Pix e no cartão; divergente é estornado automaticamente."],
            ["Dinheiro sumir numa falha do Asaas",
             "Cobrança fora de transação; falha cancela o pedido e devolve o estoque."],
        ],
        [5.2 * cm, 11.0 * cm],
    ))

    f.append(PageBreak())

    # ------------------------------------------------------ ordem de ação
    f.append(p("Se fosse eu, nesta ordem", "h1"))
    f.append(Spacer(1, 2))
    f.append(table(
        ["Quando", "O quê", "Por quê"],
        [
            ["Antes da 1ª venda",
             "Confirmar por escrito com o Asaas que o seu ramo é aceito",
             "É o risco que congela o dinheiro dos outros, não só o seu."],
            ["Antes da 1ª venda",
             "Conversar com um contador sobre PF x CNPJ",
             "A diferença de imposto é maior que a sua margem."],
            ["Antes da 1ª venda",
             "Definir prazos de moderação que você consegue cumprir",
             "Promessa quebrada vira reclamação pública."],
            ["Primeiras semanas",
             "Só Pix; cartão depois, com reserva",
             "Chargeback chega depois de o dinheiro já ter saído."],
            ["Primeiro mês",
             "Contratar bureau de verificação de idade",
             "É a maior exposição legal do projeto e o código já está pronto."],
            ["Primeiro mês",
             "Mídia em storage privado + prazo de descarte de documentos",
             "Dado sensível em disco comum é o ponto técnico mais frágil."],
            ["Ao escalar",
             "CNPJ + emissão de nota da comissão",
             "Sem isso não há como crescer sem acumular passivo."],
        ],
        [3.0 * cm, 6.6 * cm, 6.6 * cm],
    ))

    f.append(Spacer(1, 14))
    f.append(p("Uma observação final", "h1"))
    f.append(p(
        "Você me pediu sinceridade, então vou fechar com a coisa mais desconfortável: "
        "<b>é tecnicamente possível lançar hoje e faturar</b>. O site funciona, o "
        "checkout converte, o dinheiro chega. Nada do que está no item 1 e 2 impede "
        "a primeira venda — esses riscos não aparecem no dia 1, aparecem no volume, "
        "e é justamente por isso que são perigosos: quando aparecem, você já tem "
        "obrigação com vendedoras e compradores que dependem de a operação "
        "continuar de pé."))
    f.append(p(
        "Lançar em modo pequeno e controlado, enquanto resolve CNPJ e verificação "
        "de idade em paralelo, me parece um caminho defensável. Escalar antes de "
        "resolver os dois, não."))

    f.append(Spacer(1, 16))
    f.append(rule())
    f.append(p(
        "Documento gerado a partir da análise do código em "
        "<font face='Courier'>backend/</font>. Detalhes técnicos e passo a passo de "
        "configuração estão em <font face='Courier'>docs/PRODUCAO.md</font> e "
        "<font face='Courier'>backend/README.md</font>. Este material não substitui "
        "orientação de contador e advogado.", "small"))

    doc.build(f, onFirstPage=footer, onLaterPages=footer)
    print(f"PDF gerado: {OUT}")


if __name__ == "__main__":
    build()
