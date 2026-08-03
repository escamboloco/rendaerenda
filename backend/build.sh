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
# Cria/promove o administrador do painel a partir de ADMIN_EMAIL/ADMIN_PASSWORD.
python manage.py create_admin \
  || echo "AVISO: create_admin falhou; deploy continua."

# Catálogo demo: 20+ lojas, 70+ produtos, CEPs distintos, fotos públicas.
# Com SEED_PAYMENT_TEST=False, limpa demo/smoke e deixa a vitrine só com lojas reais.
if [ "${SEED_PAYMENT_TEST:-}" = "True" ] || [ "${SEED_PAYMENT_TEST:-}" = "true" ] || [ "${SEED_PAYMENT_TEST:-}" = "1" ]; then
  echo "SEED_PAYMENT_TEST ligado — povoando catálogo demo (seed_demo)."
  python manage.py seed_demo --force --skip-social \
    || echo "AVISO: seed_demo falhou; deploy continua."
else
  echo "SEED_PAYMENT_TEST desligado — removendo demo/smoke test."
  # Fail closed: produção não pode subir mantendo contas/lojas/produtos
  # fictícios por causa de uma limpeza que falhou.
  python manage.py purge_demo_and_test_data --force
fi
