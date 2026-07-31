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
