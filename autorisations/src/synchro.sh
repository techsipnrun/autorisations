#!/bin/bash
cd /home/ad/autorisations/
. .venv/bin/activate

cd /home/ad/autorisations/autorisations/src/

python3 manage.py shell -c "from instruction.views.synchro import lancer_en_arriere_plan2; lancer_en_arriere_plan2()"

deactivate
