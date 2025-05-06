# Prérequis

### Environnement

Création de l'environnement virtuel
`python -m venv .env`

Installation des librairies
`pip install -r requirements.txt`  


### Commandes Django

Pour créer l'architecture d'un projet Django :
`django-admin startproject MyDjangoProject`

Pour avoir la doc de la commande 
`django-admin help startproject`

Lancer le serveur en local (terminal ouvert à la racine de src)
`py manage.py runserver`

Faire les migrations (BDD)
`python manage.py makemigrations`
`python manage.py migrate`

Cibler une database lors de la migration
`python manage.py migrate --database {database_name}`

Revenir à la 1ere version d'une app avant les migrations
`python manage.py migrate {appName} zero

Pour créer une application
`py manage.py startapp WelcomeApp`

Créer un superuser pour se connecter à la page admin
`py manage.py createsuperuser`

Lancer les tests
`py manage.py test --keepdb -v 2`

Centraliser les fichiers statiques dans le `STATIC_ROOT` :
`py manage.py collectstatic`

Executer les tests
`py manage.py test`
`py manage.py test Appli1`
`py manage.py test Appli1.tests.fichier_de_tests`


### Architecture Projet Django 

```MyDjangoProject/src/
    app1/
        static/app1/
                    css/
                    js/
                    img/
        templates/app1/
        views.py
        models.py
        urls.py
        ...
    app2/
        static/app2/
                    css/
                    js/
                    images/
        templates/app2/
        views.py
        models.py
        urls.py
        ...
    MyDjangoProject/
        static/MyDjangoProject/
                               css/
                               js/
                               images/
        templates/MyDjangoProject/
        settings.py
        urls.py
        ...
```

### PostgreSQL

La connexion à la BDD se fait dans le fichier settings.py :
```
DATABASES = {
    'default': {
            'ENGINE': 'django.db.backends.postgresql_psycopg2',
            'OPTIONS':{ 'options': '-c search_path=monSchema' },
            'NAME': 'djangoDB',
            'USER': 'postgres',
            'PASSWORD': 'pwd',
            'HOST': 'localhost',
            'PORT': '5432',
    }
}
```
On créé les modèles, on fait les migrations et normalement nos tables apparaissent  
*Important* : Il faut modifier le search_path sur pgAdmin pour faire des requêtes sur des tables de notre schéma :
```sql
SHOW search_path;
SET SEARCH_PATH TO monSchema;
```
Car par défaut on va pointer sur le schéma `public`  
Ensuite on attribue les droits à notre user

```sql
GRANT ALL ON SCHEMA "monSchema" TO postgres
```
Très important de mettre les "" si notre schéma contient des majuscules  
Le plus simple : **ne pas mettre de majuscule dans les noms de schéma**

Pour afficher la database ou le schéma sélectionné

```sql
SELECT CURRENT_SCHEMA;
SELECT current_database();
```

