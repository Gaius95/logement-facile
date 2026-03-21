# SMS Dispatcher (option B — webhook)

**Logement Facile** envoie un `POST` JSON `{"to","message"}` vers `SMS_DISPATCH_URL` → ce service envoie le SMS (Twilio ou relais).

**Liste unique des fichiers GitHub + réglages Render :** à la racine du dépôt, fichier **`SMS_GIT_RENDER.txt`**.

Routes : `GET /health` · `POST /dispatch`
