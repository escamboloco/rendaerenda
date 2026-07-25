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
python manage.py createcachetable
