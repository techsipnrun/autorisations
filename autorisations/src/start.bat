@title Application Django
@echo off
git pull
call ..\..\.env\Scripts\activate
start "" http://127.0.0.1:8000/bancarisation
python manage.py runserver 127.0.0.1:8000
pause
