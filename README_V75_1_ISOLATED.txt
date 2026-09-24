POWERHOUSE AI V75.1 ISOLATED SHELL HOTFIX

WHY:
The old versions share one FastAPI app object. That allowed a legacy V73/V74 root page
to keep winning even when v75_app.py was deployed.

FIX:
v75_isolated_app.py creates a NEW FastAPI application.
- / is owned only by V75.1.
- entire preserved legacy app is mounted at /legacy/
- V75 APIs bridge to the existing V74.8 engine functions/data.
- no broker execution is added.

UPLOAD:
Upload these exact paths preserving static/ folder:
v75_isolated_app.py
static/v75_isolated.html
render.yaml

RENDER START COMMAND:
uvicorn v75_isolated_app:app --host 0.0.0.0 --port $PORT

VALIDATE AFTER DEPLOY:
GET /api/v75/health must show:
version 75.1
isolated_shell true

Then / must show V75.1 DYNAMITE, not V73 LTS.
