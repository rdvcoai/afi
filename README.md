# AFI - Asesor Financiero Inteligente v7.0 "God Mode"

Single-Family Office autónoma y privada con IA contextual.

## Arquitectura

El sistema está compuesto por 4 servicios principales:

1. **actual-server** - La Bóveda Financiera (Puerto 5006)
2. **chroma-db** - La Memoria Vectorial RAG (Puerto 8000)
3. **afi-core** - El Cerebro Python con Gemini (Puerto 8080)
4. **afi-whatsapp** - La Interfaz Blindada Node.js

## Requisitos

- Docker 20.10+
- Docker Compose 2.0+
- 4GB RAM mínimo
- 10GB espacio en disco

## Configuración Inicial

1. Copiar el archivo de variables de entorno:
```bash
cp .env.example .env
```

2. Editar `.env` con tus credenciales:
   - `GOOGLE_API_KEY`: Tu API key de Gemini
   - `ACTUAL_PASSWORD`: Contraseña para Actual Budget

## Despliegue

Construir y levantar todos los servicios:

```bash
docker-compose up --build
```

Para ejecutar en modo detached:

```bash
docker-compose up -d --build
```

## Verificación de Servicios

- Actual Budget: http://localhost:5006
- ChromaDB: http://localhost:8000
- AFI Brain Health: http://localhost:8080

## Estructura del Proyecto

```
/afi-monorepo
├── docker-compose.yml          # Orquestador Maestro
├── .env.example                # Plantilla de variables
├── /afi-core                   # Servicio Python (Brain)
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── /afi-whatsapp               # Servicio Node.js (Interface)
│   ├── Dockerfile
│   ├── index.js
│   └── package.json
├── /data                       # Volúmenes persistentes (NO EN GIT)
│   ├── /actual_data
│   ├── /chroma_data
│   └── /books
└── /backups                    # Backups automatizados
```

## Comandos Útiles

Ver logs de un servicio específico:
```bash
docker-compose logs -f afi-core
docker-compose logs -f afi-whatsapp
```

Detener todos los servicios:
```bash
docker-compose down
```

Eliminar volúmenes (CUIDADO - borra datos):
```bash
docker-compose down -v
```

## Sprint 1 - Criterios de Aceptación

- [x] Estructura de directorios creada
- [x] docker-compose.yml configurado
- [x] Esqueleto afi-core implementado
- [x] Esqueleto afi-whatsapp implementado
- [ ] Actual Budget accesible en localhost:5006
- [ ] AFI Brain health check respondiendo
- [ ] ChromaDB persistiendo datos

## Próximos Pasos (Sprint 2)

- Integración completa RAG con ChromaDB
- Sistema de backup con Rclone
- Implementación completa del cliente WhatsApp
- Router de prompts multi-modelo Gemini

## Soporte

Para reportar issues o contribuir, consultar con el Tech Lead del proyecto.
