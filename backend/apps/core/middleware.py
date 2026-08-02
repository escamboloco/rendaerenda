# Paths acessiveis sem age gate (ex.: a propria pagina de age gate,
# admin, estaticos, healthcheck). Tudo mais exige confirmacao.
AGE_GATE_EXEMPT_PREFIXES = (
    "/entrada/",
    "/admin/",
    "/gestao/",
    "/static/",
    "/healthz",
    "/webhooks/",
    # API responde JSON e nunca renderiza o portao - marcar a requisicao
    # aqui nao teria efeito. Autenticacao/permissao de cada view
    # (IsAuthenticated, is_age_verified) continua valendo.
    "/api/",
    # robots.txt/sitemap.xml precisam ser legiveis por crawlers sem
    # sessao/cookie - nunca colocar HTML atras do gate aqui.
    "/robots.txt",
    "/sitemap.xml",
    # Previa de link (og:image). Quem busca essa URL e o robo de card do
    # X/WhatsApp/Telegram, que nao tem sessao - atras do gate o card sai
    # sem imagem. Serve imagem, nunca HTML, e so de anuncio ja publico.
    "/og/",
)

AGE_GATE_SESSION_KEY = "age_gate_confirmed"


class AgeGateMiddleware:
    """
    Marca a requisicao quando o visitante ainda nao confirmou +18. Quem
    cobre a pagina e o `core/base.html`, com um portao opaco por cima do
    conteudo (`request.age_gate_pending`) - a resposta continua sendo a
    da propria pagina, com status 200.

    Por que NAO redirecionar: crawler nao guarda sessao. Redirecionando,
    o Googlebot e os robos de card do X/WhatsApp/Telegram levavam 302
    para /entrada/ (que e noindex) em TODA URL - o site inteiro ficava
    fora do indice e nenhum link compartilhado montava previa, apesar de
    cada pagina publica declarar `index, follow`. Servindo o mesmo HTML
    para todo mundo nao ha cloaking: humano e robo recebem exatamente a
    mesma resposta, e a classificacao adulta continua declarada no
    cabecalho (meta RTA + rating adult).

    Continua sendo so a barreira visual de entrada - NAO substitui a
    verificacao de idade real (CPF + biometria, Lei 15.211/2025) exigida
    para cadastro/compra/venda, que fica em apps.accounts.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.age_gate_pending = not request.path.startswith(
            AGE_GATE_EXEMPT_PREFIXES
        ) and not request.session.get(AGE_GATE_SESSION_KEY)

        response = self.get_response(request)

        if not request.path.startswith("/admin/"):
            response["X-Robots-Tag"] = response.get("X-Robots-Tag", "")
        return response
