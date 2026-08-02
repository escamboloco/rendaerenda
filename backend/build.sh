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
python manage.py create_admin

# Smoke test: loja + 3 itens R$ 5 com imagens (idempotente).
# Com SEED_PAYMENT_TEST=False, limpa demo/smoke e deixa a vitrine só com lojas reais.
if [ "${SEED_PAYMENT_TEST:-}" = "True" ] || [ "${SEED_PAYMENT_TEST:-}" = "true" ] || [ "${SEED_PAYMENT_TEST:-}" = "1" ]; then
  echo "SEED_PAYMENT_TEST ligado — recriando loja/itens de smoke test com imagens."
  python manage.py seed_payment_test --force --refresh-images --pix-key="${PIX_TEST_KEY:-}"
else
  echo "SEED_PAYMENT_TEST desligado — removendo demo/smoke test."
  python manage.py purge_demo_and_test_data --force
fi
