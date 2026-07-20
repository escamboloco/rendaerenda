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
