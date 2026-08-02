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

# Produção limpa: remove lojas/produtos/contas de demo e smoke test.
# Só recria a loja teste se SEED_PAYMENT_TEST estiver explicitamente ligado.
if [ "${SEED_PAYMENT_TEST:-}" = "True" ] || [ "${SEED_PAYMENT_TEST:-}" = "true" ] || [ "${SEED_PAYMENT_TEST:-}" = "1" ]; then
  echo "AVISO: SEED_PAYMENT_TEST ligado — loja de teste será recriada (não use em produção aberta)."
  python manage.py seed_payment_test --force --pix-key="${PIX_TEST_KEY:-}"
else
  python manage.py purge_demo_and_test_data --force
fi
