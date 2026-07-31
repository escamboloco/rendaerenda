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
        const resp = await fetch(window.MODERATION_REPORT_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": window.CSRF_TOKEN },
          body: JSON.stringify({
            target_type: targetType,
            object_id: objectId,
            reason: this.reason,
            details: this.details,
          }),
        });
        if (!resp.ok) throw new Error("report failed");
        this.sent = true;
      } catch (e) {
        this.error = "Não foi possível enviar a denúncia. Tente novamente.";
      } finally {
        this.loading = false;
      }
    },
  };
}

function storeCartCheckout(config) {
  const cfg = config || {};
  const isAuth = !!cfg.auth;
  const quoteUrl = cfg.quoteUrl || "/api/frete/cotacao/";
  const checkoutUrl = cfg.checkoutUrl || "/api/checkout/";
  return {
    selected: {},
    checkoutOpen: false,
    ignoreOutside: false,
    cep: "",
    freightOptions: [],
    shippingService: "",
    address: { street: "", number: "", neighborhood: "", city: "", state: "" },
    marketingOptIn: false,
    guest: { name: "", email: "", cpf: "", birth_date: "" },
    loadingQuote: false,
    loadingCheckout: false,
    error: "",
    charge: null,
    trackUrl: "",
    get selectedList() {
      return Object.values(this.selected);
    },
    get count() {
      return this.selectedList.length;
    },
    get itemsTotal() {
      return this.selectedList.reduce((sum, item) => sum + Number(item.price), 0);
    },
    get freightPrice() {
      const opt = this.freightOptions.find((o) => o.service === this.shippingService);
      return opt ? Number(opt.price) : 0;
    },
    get grandTotal() {
      return this.itemsTotal + this.freightPrice;
    },
    toggle(id, price, title) {
      if (this.selected[id]) {
        const next = { ...this.selected };
        delete next[id];
        this.selected = next;
      } else {
        this.selected = { ...this.selected, [id]: { id, price, title } };
      }
      this.freightOptions = [];
      this.shippingService = "";
      this.charge = null;
    },
    buyOne(id, price, title) {
      this.selected = { [id]: { id, price, title } };
      this.freightOptions = [];
      this.shippingService = "";
      this.charge = null;
      this.openCheckout();
    },
    openCheckout() {
      if (!this.count) return;
      this.error = "";
      // Evita o mesmo clique do botao fechar o modal via click.outside.
      this.ignoreOutside = true;
      this.checkoutOpen = true;
      this.$nextTick(() => {
        setTimeout(() => {
          this.ignoreOutside = false;
        }, 200);
      });
    },
    closeCheckout() {
      if (this.charge || this.ignoreOutside) return;
      this.checkoutOpen = false;
    },
    clear() {
      this.selected = {};
      this.freightOptions = [];
      this.shippingService = "";
      this.charge = null;
      this.checkoutOpen = false;
    },
    async quoteFreight() {
      this.error = "";
      if (!this.count) {
        this.error = "Selecione pelo menos um item.";
        return;
      }
      this.loadingQuote = true;
      try {
        const resp = await fetch(quoteUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": window.CSRF_TOKEN },
          body: JSON.stringify({
            product_ids: this.selectedList.map((i) => i.id),
            destination_cep: this.cep.replace(/\D/g, ""),
          }),
        });
        if (!resp.ok) throw new Error("quote failed");
        this.freightOptions = await resp.json();
        this.shippingService = "";
      } catch (e) {
        this.error = "Não foi possível calcular o frete. Confira o CEP.";
      } finally {
        this.loadingQuote = false;
      }
    },
    async checkout() {
      this.error = "";
      if (!this.count) {
        this.error = "Selecione pelo menos um item.";
        return;
      }
      this.loadingCheckout = true;
      try {
        const body = {
          items: this.selectedList.map((i) => ({ product_id: i.id, quantity: 1 })),
          shipping_service: this.shippingService,
          shipping_address: { cep: this.cep.replace(/\D/g, ""), ...this.address },
          payment_method: "pix",
          marketing_opt_in: !!this.marketingOptIn,
        };
        if (!isAuth) {
          body.guest_name = this.guest.name;
          body.guest_email = this.guest.email;
          body.guest_cpf = this.guest.cpf;
          body.guest_birth_date = this.guest.birth_date;
        }
        const resp = await fetch(checkoutUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": window.CSRF_TOKEN },
          body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.error =
            data.detail || Object.values(data).flat().join(" ") || "Não foi possível concluir a compra.";
          return;
        }
        this.charge = data;
        this.trackUrl = data.track_url || "";
      } catch (e) {
        this.error = "Falha de conexão. Tente de novo.";
      } finally {
        this.loadingCheckout = false;
      }
    },
  };
}

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
        const resp = await fetch("/api/pedidos-personalizados/", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": window.CSRF_TOKEN },
          body: JSON.stringify({
            store_slug: storeSlug,
            title: this.title,
            description: this.description,
            offered_price: this.price,
          }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          this.error = Array.isArray(data)
            ? data.join(" ")
            : (data.detail || Object.values(data).flat().join(" ") || "Não foi possível enviar o pedido.");
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
