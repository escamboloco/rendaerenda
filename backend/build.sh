#!/usr/bin/env bash
# Build do Render. Nao roda npm de proposito - o runtime "python" do Render
# nao tem Node.js por padrao. CSS (Tailwind) e os vendors (htmx/alpine) sao
# compilados localmente com `npm run build:css` e versionados no repo (ver
# .gitignore) - rode esse comando antes de cada deploy que mexer em
# templates/*.html ou static/css/input.css.
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate
python manage.py createcachetable || true
# Admin/seed nunca podem derrubar o web — senão /vender/ e abrir-loja caem em 502.
python manage.py create_admin \
  || echo "AVISO: create_admin falhou; deploy continua."

# Smoke test: loja + 3 itens R$ 5 com imagens (idempotente).
# Sem --refresh-images no deploy: só gera JPEG se o produto nasceu sem foto.
# Com SEED_PAYMENT_TEST=False, limpa demo/smoke e deixa a vitrine só com lojas reais.
if [ "${SEED_PAYMENT_TEST:-}" = "True" ] || [ "${SEED_PAYMENT_TEST:-}" = "true" ] || [ "${SEED_PAYMENT_TEST:-}" = "1" ]; then
  echo "SEED_PAYMENT_TEST ligado — garantindo loja/itens de smoke test."
  python manage.py seed_payment_test --force --pix-key="${PIX_TEST_KEY:-}" \
    || echo "AVISO: seed_payment_test falhou; deploy continua."
else
  echo "SEED_PAYMENT_TEST desligado — removendo demo/smoke test."
  python manage.py purge_demo_and_test_data --force \
    || echo "AVISO: purge_demo_and_test_data falhou; deploy continua."
fi
