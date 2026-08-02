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

# Cria/promove o administrador do painel a partir de ADMIN_EMAIL/ADMIN_PASSWORD.
# Idempotente e silencioso se as variaveis nao existirem.
python manage.py create_admin || true

# Loja + 3 produtos teste (R$ 5) para a primeira venda. Idempotente.
if [ "${SEED_PAYMENT_TEST:-}" = "True" ] || [ "${SEED_PAYMENT_TEST:-}" = "true" ] || [ "${SEED_PAYMENT_TEST:-}" = "1" ]; then
  python manage.py seed_payment_test --force --pix-key="${PIX_TEST_KEY:-}"
fi
