/*
 * JS do Renda & Renda.
 *
 * Carregado com defer ANTES do Alpine (tambem defer): as funcoes usadas em
 * x-data precisam existir quando o Alpine inicializa. Nada de CDN e nada de
 * eval de string vinda do servidor — a CSP e fechada em 'self'.
 */

/* ------------------------------------------------------------------ utils */

function getCsrfToken() {
  function valid(t) {
    return typeof t === "string" && t.length >= 32;
  }
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  if (match && match[1]) {
    const fromCookie = decodeURIComponent(match[1]);
    if (valid(fromCookie)) return fromCookie;
  }
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && valid(meta.content)) return meta.content;
  return (meta && meta.content) || "";
}
window.getCsrfToken = getCsrfToken;
// Compatibilidade com scripts inline antigos que leem window.CSRF_TOKEN.
window.CSRF_TOKEN = getCsrfToken();

function jsonHeaders() {
  return { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() };
}

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: jsonHeaders(),
    body: JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, data };
}

function errorMessage(data, fallback) {
  if (!data) return fallback;
  if (typeof data === "string") return data;
  if (data.detail) return data.detail;
  if (Array.isArray(data)) return data.join(" ");
  const values = Object.values(data).flat();
  return values.length ? String(values[0]) : fallback;
}

function money(value) {
  const number = Number(value || 0);
  return number.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
window.money = money;

function onlyDigits(value) {
  return (value || "").replace(/\D/g, "");
}

function maskCPF(value) {
  const d = onlyDigits(value).slice(0, 11);
  return d
    .replace(/(\d{3})(\d)/, "$1.$2")
    .replace(/(\d{3})\.(\d{3})(\d)/, "$1.$2.$3")
    .replace(/(\d{3})\.(\d{3})\.(\d{3})(\d{1,2})$/, "$1.$2.$3-$4");
}

function maskCEP(value) {
  const d = onlyDigits(value).slice(0, 8);
  return d.length > 5 ? `${d.slice(0, 5)}-${d.slice(5)}` : d;
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) {
    /* cai no fallback */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (e) {
    ok = false;
  }
  document.body.removeChild(area);
  return ok;
}

/* ------------------------------------------------------------------ sacola
 *
 * A sacola guarda SO id + quantidade. Preco, titulo, foto e estoque vem
 * sempre do servidor (POST /api/sacola/) — nada de confiar no localStorage
 * para calcular o que a pessoa vai pagar.
 */

const CART_KEY = "rr.cart.v1";

document.addEventListener("alpine:init", () => {
  Alpine.store("cart", {
    items: [],
    storeSlug: "",
    open: false,
    summary: null,
    loading: false,
    error: "",
    justAdded: "",

    init() {
      this.read();
      if (this.items.length) this.refresh();
      window.addEventListener("storage", (event) => {
        if (event.key === CART_KEY) {
          this.read();
          this.refresh();
        }
      });
    },

    read() {
      try {
        const raw = JSON.parse(localStorage.getItem(CART_KEY) || "{}");
        this.items = Array.isArray(raw.items) ? raw.items : [];
        this.storeSlug = raw.storeSlug || "";
      } catch (e) {
        this.items = [];
        this.storeSlug = "";
      }
    },

    persist() {
      try {
        localStorage.setItem(
          CART_KEY,
          JSON.stringify({ items: this.items, storeSlug: this.storeSlug })
        );
      } catch (e) {
        /* modo privado sem storage: a sacola vive so nesta aba */
      }
    },

    get count() {
      return this.items.reduce((total, item) => total + Number(item.qty || 1), 0);
    },

    get isEmpty() {
      return this.items.length === 0;
    },

    get total() {
      return this.summary ? Number(this.summary.grand_total) : 0;
    },

    has(productId) {
      return this.items.some((item) => item.id === productId);
    },

    qtyOf(productId) {
      const found = this.items.find((item) => item.id === productId);
      return found ? Number(found.qty) : 0;
    },

    /* storeSlug garante "uma loja por pedido" — regra do backend.
       addonIds são os adicionais escolhidos no anúncio ("quer com X?"). */
    add(productId, storeSlug, quantity, addonIds) {
      const qty = Number(quantity || 1);
      const addons = Array.isArray(addonIds) ? addonIds.filter(Boolean) : [];
      if (this.items.length && storeSlug && this.storeSlug && storeSlug !== this.storeSlug) {
        const replace = window.confirm(
          "Sua sacola tem itens de outra loja e cada pedido é fechado com uma loja só. Quer esvaziar e começar esta?"
        );
        if (!replace) return false;
        this.items = [];
      }
      this.storeSlug = storeSlug || this.storeSlug;
      const existing = this.items.find((item) => item.id === productId);
      if (existing) {
        existing.qty = Number(existing.qty) + qty;
        if (addons.length) {
          existing.addons = [...new Set([...(existing.addons || []), ...addons])];
        }
      } else {
        this.items.push({ id: productId, qty, addons });
      }
      this.persist();
      this.justAdded = productId;
      setTimeout(() => {
        if (this.justAdded === productId) this.justAdded = "";
      }, 1800);
      this.refresh();
      return true;
    },

    setQty(productId, quantity) {
      const qty = Math.max(0, Number(quantity || 0));
      if (!qty) return this.remove(productId);
      const existing = this.items.find((item) => item.id === productId);
      if (existing) existing.qty = qty;
      this.persist();
      this.refresh();
    },

    remove(productId) {
      this.items = this.items.filter((item) => item.id !== productId);
      if (!this.items.length) this.storeSlug = "";
      this.persist();
      this.refresh();
    },

    clear() {
      this.items = [];
      this.storeSlug = "";
      this.summary = null;
      this.persist();
    },

    openDrawer() {
      this.open = true;
      this.refresh();
      document.body.classList.add("overflow-hidden");
    },

    closeDrawer() {
      this.open = false;
      document.body.classList.remove("overflow-hidden");
    },

    async refresh() {
      if (!this.items.length) {
        this.summary = null;
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        const { ok, data } = await postJSON("/api/sacola/", { items: this.items });
        if (!ok) {
          this.error = errorMessage(data, "Não foi possível carregar sua sacola.");
          return;
        }
        this.summary = data;
        // Item que saiu do ar sai da sacola sozinho, sem travar o checkout.
        if (data.unavailable && data.unavailable.length) {
          const gone = new Set(data.unavailable.map((item) => item.id));
          this.items = this.items.filter((item) => !gone.has(item.id));
          this.persist();
        }
        // Alinha as quantidades ao estoque real devolvido pelo servidor.
        (data.items || []).forEach((serverItem) => {
          const local = this.items.find((item) => item.id === serverItem.id);
          if (local && Number(local.qty) !== Number(serverItem.qty)) {
            local.qty = Number(serverItem.qty);
            this.persist();
          }
        });
      } catch (e) {
        this.error = "Falha de conexão ao carregar a sacola.";
      } finally {
        this.loading = false;
      }
    },
  });
});

/* -------------------------------------------------------------- componentes */

/* Botao "Adicionar" / "Comprar agora" dos cards de anuncio. */
function buyButton(productId, storeSlug) {
  return {
    added: false,
    add() {
      if (Alpine.store("cart").add(productId, storeSlug, 1)) {
        this.added = true;
        Alpine.store("cart").openDrawer();
        setTimeout(() => {
          this.added = false;
        }, 1600);
      }
    },
    buyNow() {
      if (Alpine.store("cart").add(productId, storeSlug, 1)) {
        window.location.href = "/finalizar/";
      }
    },
  };
}

/* Caixa de compra da pagina do anuncio: adicionais + total ao vivo. */
function productBuyBox(config) {
  const cfg = config || {};
  return {
    productId: cfg.productId,
    storeSlug: cfg.storeSlug,
    basePrice: Number(cfg.price || 0),
    addons: cfg.addons || [],
    selected: [],
    added: false,

    toggleAddon(id) {
      this.selected = this.selected.includes(id)
        ? this.selected.filter((item) => item !== id)
        : [...this.selected, id];
    },

    isSelected(id) {
      return this.selected.includes(id);
    },

    get total() {
      return this.addons
        .filter((addon) => this.selected.includes(addon.id))
        .reduce((sum, addon) => sum + Number(addon.price), this.basePrice);
    },

    get totalLabel() {
      return money(this.total);
    },

    add() {
      if (Alpine.store("cart").add(this.productId, this.storeSlug, 1, this.selected)) {
        this.added = true;
        Alpine.store("cart").openDrawer();
        setTimeout(() => {
          this.added = false;
        }, 1600);
      }
    },

    buyNow() {
      if (Alpine.store("cart").add(this.productId, this.storeSlug, 1, this.selected)) {
        window.location.href = "/finalizar/";
      }
    },
  };
}

/* Perguntas publicas no anuncio. */
function questionForm(productId) {
  return {
    text: "",
    loading: false,
    sent: false,
    error: "",
    async submit() {
      this.error = "";
      if (this.text.trim().length < 5) {
        this.error = "Escreva sua pergunta.";
        return;
      }
      this.loading = true;
      try {
        const { ok, data } = await postJSON(`/api/anuncios/${productId}/perguntas/`, {
          question: this.text,
        });
        if (!ok) {
          this.error = errorMessage(data, "Não foi possível enviar a pergunta.");
          return;
        }
        this.sent = true;
        this.text = "";
      } catch (e) {
        this.error = "Falha de conexão. Tente de novo.";
      } finally {
        this.loading = false;
      }
    },
  };
}

/* Carrossel das prateleiras da vitrine.
 *
 * Scroll nativo com scroll-snap (o navegador cuida do gesto de toque e do
 * momentum) + setas e barra de progresso para desktop. Nada de biblioteca:
 * carrossel em JS costuma quebrar acessibilidade e teclado, e aqui o
 * conteudo continua sendo uma lista rolavel de verdade. */
function carousel() {
  return {
    canPrev: false,
    canNext: false,
    progress: 0,

    init() {
      this.$nextTick(() => this.measure());
      // Imagem que carrega depois muda a largura total da trilha.
      window.addEventListener("resize", () => this.measure(), { passive: true });
    },

    measure() {
      const track = this.$refs.track;
      if (!track) return;
      const max = track.scrollWidth - track.clientWidth;
      this.canPrev = track.scrollLeft > 4;
      this.canNext = track.scrollLeft < max - 4;
      this.progress = max > 0 ? Math.min(100, (track.scrollLeft / max) * 100) : 0;
    },

    /* Avanca ~85% da area visivel: deixa um item parcialmente a mostra,
       que e o que sinaliza "tem mais coisa" melhor que qualquer seta. */
    scrollBy(direction) {
      const track = this.$refs.track;
      if (!track) return;
      track.scrollBy({ left: direction * track.clientWidth * 0.85, behavior: "smooth" });
    },
  };
}

/* Galeria da pagina de produto. */
function productGallery(images) {
  return {
    images: images || [],
    index: 0,
    get current() {
      return this.images[this.index] || "";
    },
    select(i) {
      this.index = i;
    },
    next() {
      this.index = (this.index + 1) % Math.max(this.images.length, 1);
    },
    prev() {
      this.index = (this.index - 1 + this.images.length) % Math.max(this.images.length, 1);
    },
  };
}

/* Funil de checkout (/finalizar/). */
function checkoutFunnel(config) {
  const cfg = config || {};
  return {
    isAuth: !!cfg.auth,
    checkoutUrl: cfg.checkoutUrl || "/api/checkout/",
    step: 1,
    loading: false,
    error: "",
    fieldErrors: {},
    cepLoading: false,
    cepError: "",
    freight: null,
    freightLoading: false,
    marketingOptIn: false,
    paymentMethod: "pix",
    guest: { name: "", email: "", cpf: "", birth_date: "" },
    address: {
      cep: "",
      street: "",
      number: "",
      complement: "",
      neighborhood: "",
      city: "",
      state: "",
    },
    charge: null,
    orderToken: "",
    paid: false,
    expired: false,
    copied: false,
    secondsLeft: 0,
    pollTimer: null,
    clockTimer: null,

    init() {
      this.restore();
      this.$watch("guest", () => this.remember(), { deep: true });
      this.$watch("address", () => this.remember(), { deep: true });
    },

    /* Recupera o que a pessoa ja digitou — recarregar a pagina no meio do
       checkout e um dos maiores motivos de abandono. */
    restore() {
      try {
        const saved = JSON.parse(sessionStorage.getItem("rr.checkout") || "{}");
        if (saved.guest) Object.assign(this.guest, saved.guest);
        if (saved.address) Object.assign(this.address, saved.address);
      } catch (e) {
        /* ignora */
      }
    },

    remember() {
      try {
        sessionStorage.setItem(
          "rr.checkout",
          JSON.stringify({ guest: this.guest, address: this.address })
        );
      } catch (e) {
        /* ignora */
      }
    },

    get cart() {
      return Alpine.store("cart");
    },

    get summary() {
      return this.cart.summary;
    },

    get totalLabel() {
      return money(this.orderTotal);
    },

    formatCPF() {
      this.guest.cpf = maskCPF(this.guest.cpf);
    },

    formatCEP() {
      this.address.cep = maskCEP(this.address.cep);
    },

    async lookupCep() {
      const cep = onlyDigits(this.address.cep);
      this.cepError = "";
      if (cep.length !== 8) return;
      this.cepLoading = true;
      try {
        const response = await fetch(`/api/cep/${cep}/`, { credentials: "same-origin" });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          this.cepError = data.detail || "CEP não encontrado. Preencha o endereço manualmente.";
          return;
        }
        this.address.street = data.street || this.address.street;
        this.address.neighborhood = data.neighborhood || this.address.neighborhood;
        this.address.city = data.city || this.address.city;
        this.address.state = data.state || this.address.state;
        this.$nextTick(() => {
          const numberField = document.getElementById("address-number");
          if (numberField && !this.address.number) numberField.focus();
        });
        this.quoteFreight();
      } catch (e) {
        this.cepError = "Não foi possível consultar o CEP. Preencha manualmente.";
      } finally {
        this.cepLoading = false;
      }
    },

    /* Frete so aparece depois do CEP: e o unico momento em que da para
       calcular de verdade (origem = CEP da vendedora, destino = o dela). */
    async quoteFreight() {
      const cep = onlyDigits(this.address.cep);
      const items = this.cart.items;
      if (cep.length !== 8 || !items.length) return;
      this.freightLoading = true;
      try {
        const { ok, data } = await postJSON("/api/frete/cotacao/", {
          destination_cep: cep,
          product_ids: items.map((item) => item.id),
        });
        if (!ok || !Array.isArray(data) || !data.length) {
          this.freight = null;
          return;
        }
        this.freight = data[0];
      } catch (e) {
        this.freight = null;
      } finally {
        this.freightLoading = false;
      }
    },

    get freightPrice() {
      return this.freight ? Number(this.freight.price) : 0;
    },

    get orderTotal() {
      const items = this.summary ? Number(this.summary.grand_total) : 0;
      return items + this.freightPrice;
    },

    validateIdentity() {
      this.fieldErrors = {};
      if (this.isAuth) return true;
      if (!this.guest.name.trim() || this.guest.name.trim().split(" ").length < 2) {
        this.fieldErrors.name = "Informe seu nome completo.";
      }
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(this.guest.email.trim())) {
        this.fieldErrors.email = "Informe um e-mail válido.";
      }
      if (onlyDigits(this.guest.cpf).length !== 11) {
        this.fieldErrors.cpf = "CPF incompleto.";
      }
      if (!this.guest.birth_date) {
        this.fieldErrors.birth_date = "Informe sua data de nascimento.";
      } else {
        const birth = new Date(this.guest.birth_date + "T00:00:00");
        const adult = new Date();
        adult.setFullYear(adult.getFullYear() - 18);
        if (birth > adult) this.fieldErrors.birth_date = "A compra é permitida apenas para maiores de 18 anos.";
      }
      return Object.keys(this.fieldErrors).length === 0;
    },

    /* Sacola só de conteúdo digital não tem entrega física. */
    get needsShipping() {
      return !this.summary || this.summary.requires_shipping !== false;
    },

    validateAddress() {
      this.fieldErrors = {};
      if (!this.needsShipping) return true;
      if (onlyDigits(this.address.cep).length !== 8) this.fieldErrors.cep = "CEP incompleto.";
      if (!this.address.street.trim()) this.fieldErrors.street = "Informe a rua.";
      if (!this.address.number.trim()) this.fieldErrors.number = "Informe o número.";
      if (!this.address.neighborhood.trim()) this.fieldErrors.neighborhood = "Informe o bairro.";
      if (!this.address.city.trim()) this.fieldErrors.city = "Informe a cidade.";
      if (this.address.state.trim().length !== 2) this.fieldErrors.state = "UF com 2 letras.";
      return Object.keys(this.fieldErrors).length === 0;
    },

    goToAddress() {
      this.error = "";
      if (!this.validateIdentity()) return;
      this.step = 2;
      window.scrollTo({ top: 0, behavior: "smooth" });
    },

    backToIdentity() {
      this.step = 1;
      window.scrollTo({ top: 0, behavior: "smooth" });
    },

    async pay() {
      this.error = "";
      if (!this.validateAddress()) return;
      if (!this.cart.items.length) {
        this.error = "Sua sacola está vazia.";
        return;
      }
      this.loading = true;
      try {
        const body = {
          items: this.cart.items.map((item) => ({
            product_id: item.id,
            quantity: item.qty,
            addon_ids: item.addons || [],
          })),
          shipping_service: "pac",
          shipping_address: this.needsShipping
            ? {
                cep: onlyDigits(this.address.cep),
                street: this.address.street.trim(),
                number: this.address.number.trim(),
                complement: this.address.complement.trim(),
                neighborhood: this.address.neighborhood.trim(),
                city: this.address.city.trim(),
                state: this.address.state.trim().toUpperCase(),
              }
            : {},
          payment_method: this.paymentMethod,
          marketing_opt_in: !!this.marketingOptIn,
        };
        if (!this.isAuth) {
          body.guest_name = this.guest.name.trim();
          body.guest_email = this.guest.email.trim();
          body.guest_cpf = onlyDigits(this.guest.cpf);
          body.guest_birth_date = this.guest.birth_date;
        }
        const { ok, data } = await postJSON(this.checkoutUrl, body);
        if (!ok) {
          this.error = errorMessage(data, "Não foi possível gerar o pagamento.");
          this.cart.refresh();
          return;
        }
        this.charge = data;
        this.orderToken = data.access_token || "";
        this.step = 3;
        this.cart.clear();
        // Cartão é pago na página do Asaas: abre já, sem um clique a mais.
        if (this.paymentMethod === "credit_card" && data.payment_url) {
          window.open(data.payment_url, "_blank", "noopener");
        }
        try {
          sessionStorage.removeItem("rr.checkout");
        } catch (e) {
          /* ignora */
        }
        window.scrollTo({ top: 0, behavior: "smooth" });
        this.startCountdown(data.expires_at);
        this.startPolling();
      } catch (e) {
        this.error = "Falha de conexão. Nada foi cobrado — tente de novo.";
      } finally {
        this.loading = false;
      }
    },

    startCountdown(expiresAt) {
      if (!expiresAt) return;
      const deadline = new Date(expiresAt).getTime();
      const tick = () => {
        this.secondsLeft = Math.max(0, Math.round((deadline - Date.now()) / 1000));
        if (this.secondsLeft <= 0) {
          clearInterval(this.clockTimer);
          if (!this.paid) this.expired = true;
        }
      };
      tick();
      this.clockTimer = setInterval(tick, 1000);
    },

    get countdown() {
      const minutes = Math.floor(this.secondsLeft / 60);
      const seconds = this.secondsLeft % 60;
      return `${minutes}:${String(seconds).padStart(2, "0")}`;
    },

    startPolling() {
      if (!this.orderToken) return;
      const poll = async () => {
        try {
          const response = await fetch(`/api/pedido/${this.orderToken}/status/`, {
            credentials: "same-origin",
          });
          if (!response.ok) return;
          const data = await response.json();
          if (data.paid) {
            this.paid = true;
            clearInterval(this.pollTimer);
            clearInterval(this.clockTimer);
          } else if (data.expired) {
            this.expired = true;
            clearInterval(this.pollTimer);
          }
        } catch (e) {
          /* silencioso: e so polling */
        }
      };
      this.pollTimer = setInterval(poll, 4000);
      poll();
    },

    async copyPix() {
      if (!this.charge || !this.charge.pix_copy_paste) return;
      this.copied = await copyText(this.charge.pix_copy_paste);
      setTimeout(() => {
        this.copied = false;
      }, 2500);
    },
  };
}

/* Pagina do pedido (/pedido/<token>/) — reexibe o Pix e confirma sozinha. */
function orderTracker(token, awaitingPayment) {
  return {
    paid: !awaitingPayment,
    expired: false,
    copied: false,
    timer: null,

    init() {
      if (awaitingPayment) {
        this.timer = setInterval(() => this.check(), 5000);
        this.check();
      }
    },

    async check() {
      try {
        const response = await fetch(`/api/pedido/${token}/status/`, { credentials: "same-origin" });
        if (!response.ok) return;
        const data = await response.json();
        if (data.paid) {
          this.paid = true;
          clearInterval(this.timer);
          window.location.reload();
        } else if (data.expired) {
          this.expired = true;
          clearInterval(this.timer);
        }
      } catch (e) {
        /* silencioso */
      }
    },

    async copy(text) {
      this.copied = await copyText(text);
      setTimeout(() => {
        this.copied = false;
      }, 2500);
    },
  };
}

/* Liberacao da custodia na pagina do pedido. */
function orderRelease(token) {
  return {
    loading: false,
    error: "",
    async send(action) {
      this.loading = true;
      this.error = "";
      try {
        const { ok, data } = await postJSON(`/api/pedido/${token}/confirmar/`, { action });
        if (!ok) {
          this.error = errorMessage(data, "Não foi possível registrar sua resposta.");
          return;
        }
        window.location.reload();
      } catch (e) {
        this.error = "Falha de conexão. Tente de novo.";
      } finally {
        this.loading = false;
      }
    },
    confirm() {
      this.send("confirm");
    },
    dispute() {
      if (!window.confirm("Abrir contestação? O pagamento fica travado até a moderação analisar.")) return;
      this.send("dispute");
    },
  };
}

/* Conversa privada do pedido (comprador <-> vendedora). */
function orderChat(token) {
  return {
    messages: [],
    role: "buyer",
    text: "",
    loading: false,
    sending: false,
    error: "",
    timer: null,
    // Atalhos de primeira mensagem: quem abre o chat costuma travar no
    // "o que eu escrevo?", e conversa iniciada evita contestacao depois.
    suggestions: [
      "Oi! Quando você consegue postar?",
      "Pode me avisar o código de rastreio?",
      "Confirma o tamanho da peça, por favor?",
    ],

    formatTime(value) {
      if (!value) return "";
      const date = new Date(value);
      if (isNaN(date.getTime())) return "";
      const today = new Date();
      const sameDay = date.toDateString() === today.toDateString();
      return sameDay
        ? date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
        : date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
    },

    init() {
      this.load();
      // Sem websocket: o pedido tem duas pessoas conversando, um poll
      // lento resolve sem custo de infra.
      this.timer = setInterval(() => this.load(), 20000);
    },

    async load() {
      try {
        const response = await fetch(`/api/pedido/${token}/mensagens/`, {
          credentials: "same-origin",
        });
        if (!response.ok) return;
        const data = await response.json();
        const isFirstLoad = !this.messages.length;
        const grew = data.messages.length > this.messages.length;
        this.messages = data.messages;
        this.role = data.role;
        if (isFirstLoad || grew) this.scrollToEnd();
      } catch (e) {
        /* silencioso: e so atualizacao de fundo */
      }
    },

    scrollToEnd() {
      this.$nextTick(() => {
        const box = document.getElementById("chat-scroll");
        if (box) box.scrollTop = box.scrollHeight;
      });
    },

    async send() {
      const body = this.text.trim();
      if (!body) return;
      this.sending = true;
      this.error = "";
      try {
        const { ok, data } = await postJSON(`/api/pedido/${token}/mensagens/`, { body });
        if (!ok) {
          this.error = errorMessage(data, "Não foi possível enviar.");
          return;
        }
        this.messages = [...this.messages, data];
        this.text = "";
        this.scrollToEnd();
      } catch (e) {
        this.error = "Falha de conexão. Tente de novo.";
      } finally {
        this.sending = false;
      }
    },
  };
}

/* Denuncia de anuncio/loja. */
function reportModal(targetType, objectId) {
  return {
    open: false,
    loading: false,
    sent: false,
    error: "",
    reason: "underage_suspicion",
    details: "",
    async submit() {
      this.loading = true;
      this.error = "";
      try {
        const { ok } = await postJSON(window.MODERATION_REPORT_URL, {
          target_type: targetType,
          object_id: objectId,
          reason: this.reason,
          details: this.details,
        });
        if (!ok) throw new Error("report failed");
        this.sent = true;
      } catch (e) {
        this.error = "Não foi possível enviar a denúncia. Tente novamente.";
      } finally {
        this.loading = false;
      }
    },
  };
}

/* Pedido personalizado para a vendedora. */
function customRequestModal(storeSlug) {
  return {
    open: false,
    sent: false,
    loading: false,
    error: "",
    title: "",
    description: "",
    price: "",
    async submit() {
      this.loading = true;
      this.error = "";
      try {
        const { ok, data } = await postJSON("/api/pedidos-personalizados/", {
          store_slug: storeSlug,
          title: this.title,
          description: this.description,
          offered_price: this.price,
        });
        if (!ok) {
          this.error = errorMessage(data, "Não foi possível enviar o pedido.");
          return;
        }
        this.sent = true;
      } catch (e) {
        this.error = "Erro de conexão. Tente novamente.";
      } finally {
        this.loading = false;
      }
    },
  };
}
