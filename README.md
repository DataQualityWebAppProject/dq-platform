# DQ Platform — Data Quality Platform

Plataforma de gestión de calidad de datos en AWS. Permite subir datasets (CSV),
definir reglas de calidad en lenguaje natural (interpretadas y convertidas a
código Python por IA), ejecutar validaciones, generar scripts de limpieza, y
producir reportes ejecutivos — todo con generación de código asistida por
Amazon Bedrock (Nova Lite).

## Arquitectura

```
Browser → EC2 (FastAPI) → {
  /auth/*                        → Cognito (server-side, httpOnly cookie)
  /api/catalog, /api/rules,
  /api/validations, /api/cleaning,
  /api/reports                   → DynamoDB + S3 + Bedrock (directo)
  /api/*  (fallback)              → API Gateway → Lambda
}
```

- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS v4, servido como
  build estático desde el mismo servidor FastAPI.
- **Backend**: FastAPI (`server/app.py`) corriendo en EC2 vía systemd,
  con acceso directo a DynamoDB, S3 y Bedrock usando un IAM role de instancia.
- **Infraestructura como código**: AWS CDK (Python) en `infra/`, con stacks
  separados para VPC, Cognito, DynamoDB, S3, IAM, Lambda y API Gateway.
- **Servicios backend desplegados como Lambda** (`services/`): gobernanza de
  catálogos, reglas, validación, limpieza, anomalías y reportes — invocables
  vía API Gateway como ruta alternativa al acceso directo del servidor.

## Estructura del repositorio

```
infra/          CDK stacks (VPC, Cognito, DynamoDB, S3, IAM, Lambda, API Gateway)
server/         Servidor FastAPI que sirve el frontend y expone la API
frontend/       Aplicación React (Dashboard, Catalog, Rules, Validation, Cleaning, Reports)
services/       Handlers Lambda por dominio (governance, rules, validation, cleaning, anomalies, reporting)
dqplatform.service   Unit de systemd para correr el servidor FastAPI en EC2
EC2_DEPLOYMENT.md    Detalles de la instancia EC2 y pasos de despliegue
```

## Funcionalidades principales

- **Upload**: sube CSV/Parquet, detecta separador, infiere tipos de columna,
  permite editar el esquema antes de confirmar.
- **Rules**: define reglas de calidad en lenguaje natural con alcance de
  Catálogo → Tabla → Columna; Nova Lite las interpreta y genera el código
  Python de validación correspondiente.
- **Validation**: ejecuta las reglas activas contra una tabla y muestra el
  puntaje de calidad por regla y general.
- **Cleaning**: genera (con IA) y ejecuta scripts de limpieza sobre los datos,
  mostrando filas originales/limpiadas/eliminadas.
- **Reports**: genera reportes ejecutivos en Markdown (renderizados como HTML)
  a partir del estado del catálogo y sus reglas.
- **Anomalies**: entrenamiento de un autoencoder para detección de anomalías
  (pendiente de aprobación de cuota GPU en SageMaker).

## Despliegue

Ver [`EC2_DEPLOYMENT.md`](./EC2_DEPLOYMENT.md) para detalles de la instancia
EC2 activa, cómo actualizar el despliegue, y cómo correr el servidor en local.

Para desplegar/actualizar la infraestructura AWS:

```bash
cd infra
pip install -r requirements.txt
cdk deploy --all --require-approval never
```

Para construir el frontend:

```bash
cd frontend
npm install
npm run build
```

## Desarrollo local

```bash
# Backend
cd server
pip install -r requirements.txt
uvicorn app:app --reload --port 8000

# Frontend (en otra terminal)
cd frontend
npm install
npm run dev
```
