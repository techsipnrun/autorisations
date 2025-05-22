import os
from pathlib import Path
from dotenv import load_dotenv

#BASE_DIR = autorisations\autorisations\src
BASE_DIR = Path(__file__).resolve().parent.parent


# Chemin du fichier .env en fonction de l'environnement
ENVIRONMENT = os.getenv("DJANGO_ENV", "dev")  # dev par défaut, DJANGO_ENV=prod python manage.py runserver pour lancer en prod
dotenv_path = BASE_DIR / f".env.{ENVIRONMENT}"
load_dotenv(dotenv_path)



# SECRET_KEY = 'django-insecure-2#ru%4)n-z4&+jv-6m!6+6j1&s6#ro6+t*l_ldg-5pjif*97is'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'autorisations',
    'authent',
    'instruction',
    'BDD',
    'DS',
    'drf_yasg', #Swagger
    'django_filters',
    'rest_framework.authtoken',
    'leaflet',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'BDD.middleware.API_PG_LogMiddleware',
]

ROOT_URLCONF = 'autorisations.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'instruction/templates/instruction'), os.path.join(BASE_DIR, 'authent/templates/authent'), os.path.join(BASE_DIR, 'autorisations/templates/autorisations'),],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'instruction.views.views.mes_dossiers_a_traiter_count',
                'instruction.context_processors.breadcrumb_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'autorisations.wsgi.application'


# Database

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('BDD_NAME'),
        'USER': os.environ.get('BDD_USER'),
        'PASSWORD': os.environ.get('BDD_PASSWORD'),
        'HOST': os.environ.get('BDD_HOSTNAME'),
        'PORT': os.environ.get('BDD_PORT'),
        'OPTIONS': {
            'options': '-c search_path=public,avis,documents,instruction,utilisateurs'
        },
        'TEST': {
            'NAME': 'test_autorisations',  # Base de test
            'OPTIONS': {
                'options': '-c search_path=public,avis,documents,instruction,utilisateurs'
            },
        }
    }
}



# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'fr'

TIME_ZONE = "Indian/Reunion"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

STATIC_URL = 'static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'authent/static/'),
    os.path.join(BASE_DIR, 'instruction/static/'),
]

# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Redirige vers la page d'accueil après connexion
LOGIN_REDIRECT_URL = '/'
# Redirige vers la page de login après déconnexion
LOGOUT_REDIRECT_URL = '/login/'



LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
       
        'ldap_file': {  # fichier pour les logs LDAP
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'logs/active_directory.log',  # Path LDAP Logs
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'app_file': {  # fichier pour les logs Lecture/Ecriture fichiers par l'application
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': 'logs/app.log',  # Path LDAP Logs
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'apiDS_file': { # fichier pour les logs de l'API DS
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/apiDS.log', 
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'apiPG_file': { # fichier pour les logs de l'API Postgres
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/apiPG.log', 
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'ORM_django_file': { # fichier pour les logs de l'ORM Django
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'logs/ORM_django.log', 
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'console': {  # pour affichage en console
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        
        'LDAP_LOGS': {  # logger pour Active Directory
            'handlers': ['ldap_file', 'console'],
            'level': 'DEBUG',  # Permet de tout capturer (INFO, WARNING, ERROR, etc.)
            'propagate': False,
        },
        'API_DS': {  # logger pour API DS
            'handlers': ['apiDS_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'API_PG': {
            'handlers': ['apiPG_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'ORM_DJANGO': {
            'handlers': ['ORM_django_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'APP': {
            'handlers': ['app_file'],
            'level': 'INFO',
            'propagate': False,
        }
    }
}

#Choix entre l'authentification LDAP ou classique via Django

# AUTHENTICATION_BACKENDS = ['authent.LDAP.ldap_backend.LDAPBackend', 'django.contrib.auth.backends.ModelBackend',]
AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend', 'authent.LDAP.ldap_backend.LDAPBackend'] #Si on veut verif les users locaux avant LDAP


#SWAGGER
ACCOUNT_LOGOUT_ON_GET= True

SWAGGER_SETTINGS = {
    'LOGIN_URL': '/login/',
    'LOGOUT_URL': '/swagger/logout/',
    'USE_SESSION_AUTH': True, # Active l'authentification basée sur la session
    'TRANSLATIONS': {
        'en': 'English',
        'fr': 'Français'
    },
    'SECURITY_DEFINITIONS': {
        'Token': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header',
            'description': "Ajoutez '<votre_token>' dans l'en-tête",
        },
    },
}

# Parametrage de l'API Postgres
REST_FRAMEWORK = {

    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',  # Exige une authentification par défaut
    ],

    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',  # Auth par token
        'rest_framework.authentication.SessionAuthentication', 
    ],

    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
}


