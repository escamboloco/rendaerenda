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
  const checkoutUrl = cfg.checkoutUrl || "/api/checkout/";
  return {
    selected: {},
    checkoutOpen: false,
    ignoreOutside: false,
    address: {
      cep: "",
      street: "",
      number: "",
      neighborhood: "",
      city: "",
      state: "",
    },
    marketingOptIn: false,
    guest: { name: "", email: "", cpf: "", birth_date: "" },
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
    get grandTotal() {
      return this.itemsTotal;
    },
    toggle(id, price, title) {
      if (this.selected[id]) {
        const next = { ...this.selected };
        delete next[id];
        this.selected = next;
      } else {
        this.selected = { ...this.selected, [id]: { id, price, title } };
      }
      this.charge = null;
    },
    buyOne(id, price, title) {
      this.selected = { [id]: { id, price, title } };
      this.charge = null;
      this.openCheckout();
    },
    openCheckout() {
      if (!this.count) return;
      this.error = "";
      this.ignoreOutside = true;
      this.checkoutOpen = true;
      document.body.style.overflow = "hidden";
      this.$nextTick(() => {
        setTimeout(() => {
          this.ignoreOutside = false;
        }, 250);
      });
    },
    closeCheckout() {
      if (this.charge || this.ignoreOutside) return;
      this.checkoutOpen = false;
      document.body.style.overflow = "";
    },
    clear() {
      this.selected = {};
      this.charge = null;
      this.checkoutOpen = false;
      document.body.style.overflow = "";
    },
    async checkout() {
      this.error = "";
      if (!this.count) {
        this.error = "Selecione pelo menos um item.";
        return;
      }
      const cep = (this.address.cep || "").replace(/\D/g, "");
      if (cep.length !== 8) {
        this.error = "Informe um CEP válido com 8 dígitos.";
        return;
      }
      for (const field of ["street", "number", "neighborhood", "city", "state"]) {
        if (!(this.address[field] || "").trim()) {
          this.error = "Preencha o endereço completo.";
          return;
        }
      }
      if (!isAuth) {
        if (!(this.guest.name || "").trim() || !(this.guest.email || "").trim()) {
          this.error = "Informe nome e e-mail.";
          return;
        }
        if ((this.guest.cpf || "").replace(/\D/g, "").length !== 11) {
          this.error = "Informe um CPF válido.";
          return;
        }
        if (!this.guest.birth_date) {
          this.error = "Informe a data de nascimento.";
          return;
        }
      }
      this.loadingCheckout = true;
      try {
        const body = {
          items: this.selectedList.map((i) => ({ product_id: i.id, quantity: 1 })),
          shipping_service: "pac",
          shipping_address: {
            cep,
            street: this.address.street.trim(),
            number: this.address.number.trim(),
            neighborhood: this.address.neighborhood.trim(),
            city: this.address.city.trim(),
            state: this.address.state.trim().toUpperCase(),
          },
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
        if (data.payment_url) {
          window.open(data.payment_url, "_blank", "noopener");
        }
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
